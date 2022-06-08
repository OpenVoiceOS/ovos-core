import time
from threading import Thread, Lock

from mycroft_bus_client import Message

from mycroft.audio.tts import TTSFactory
from mycroft.configuration import Configuration
from mycroft.metrics import report_timing, Stopwatch
from mycroft.audio.audioservice import AudioService
from mycroft.util import check_for_signal, start_message_bus_client
from mycroft.util.log import LOG
from mycroft.util.process_utils import ProcessStatus, StatusCallbackMap


def on_ready():
    LOG.info('Audio service is ready.')


def on_alive():
    LOG.info('Audio service is alive.')


def on_started():
    LOG.info('Audio service started.')


def on_error(e='Unknown'):
    LOG.error(f'Audio service failed to launch ({e}).')


def on_stopping():
    LOG.info('Audio service is shutting down...')


class SpeechService(Thread):
    def __init__(self, ready_hook=on_ready, error_hook=on_error,
                 stopping_hook=on_stopping, alive_hook=on_alive,
                 started_hook=on_started, watchdog=lambda: None, bus=None):
        super(SpeechService, self).__init__()

        LOG.info("Starting Audio Service")
        callbacks = StatusCallbackMap(on_ready=ready_hook, on_error=error_hook,
                                      on_stopping=stopping_hook,
                                      on_alive=alive_hook,
                                      on_started=started_hook)
        self.status = ProcessStatus('audio', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration()
        self.tts = None
        self._tts_hash = None
        self.lock = Lock()
        self.fallback_tts = None
        self._fallback_tts_hash = None
        self._last_stop_signal = 0

        whitelist = ['mycroft.audio.service']
        self.bus = bus or start_message_bus_client("AUDIO",
                                                   whitelist=whitelist)
        self.status.bind(self.bus)
        self.init_messagebus()

        try:
            self._maybe_reload_tts()
            Configuration.set_config_watcher(self._maybe_reload_tts)
        except Exception as e:
            LOG.exception(e)
            self.status.set_error(e)

        try:
            self.audio = AudioService(self.bus)
        except Exception as e:
            LOG.exception(e)
            self.status.set_error(e)

    def run(self):
        if self.audio.wait_for_load():
            if len(self.audio.service) == 0:
                LOG.warning('No audio backends loaded! '
                            'Audio playback is not available')
                LOG.info("Running audio service in TTS only mode")
        # If at least TTS exists, report ready
        if self.tts:
            self.status.set_ready()
        else:
            self.status.set_error('No TTS loaded')

    def handle_speak(self, message):
        """Handle "speak" message

        Parse sentences and invoke text to speech service.
        """

        # if the message is targeted and audio is not the target don't
        # don't synthesise speech
        message.context = message.context or {}
        if message.context.get('destination') and not \
                ('debug_cli' in message.context['destination'] or
                 'audio' in message.context['destination']):
            return

        # Get conversation ID
        if message.context and 'ident' in message.context:
            ident = message.context['ident']
        else:
            ident = 'unknown'

        with self.lock:
            stopwatch = Stopwatch()
            stopwatch.start()

            utterance = message.data['utterance']
            listen = message.data.get('expect_response', False)
            self.execute_tts(utterance, ident, listen)

            stopwatch.stop()

        report_timing(ident, 'speech', stopwatch,
                      {'utterance': utterance,
                       'tts': self.tts.__class__.__name__})

    def _maybe_reload_tts(self):
        config = self.config.get("tts", {})

        # update TTS object if configuration has changed
        if not self._tts_hash or self._tts_hash != config.get("module", ""):
            if self.tts:
                self.tts.shutdown()
            # Create new tts instance
            LOG.info("(re)loading TTS engine")
            self.tts = TTSFactory.create(config)
            self.tts.init(self.bus)
            self._tts_hash = config.get("module", "")

        # if fallback TTS is the same as main TTS dont load it
        if config.get("module", "") == config.get("fallback_module", ""):
            return

        if not self._fallback_tts_hash or \
                self._fallback_tts_hash != config.get("fallback_module", ""):
            if self.fallback_tts:
                self.fallback_tts.shutdown()
            # Create new tts instance
            LOG.info("(re)loading fallback TTS engine")
            self._get_tts_fallback()
            self._fallback_tts_hash = config.get("fallback_module", "")

    def execute_tts(self, utterance, ident, listen=False):
        """Mute mic and start speaking the utterance using selected tts backend.

        Args:
            utterance:  The sentence to be spoken
            ident:      Ident tying the utterance to the source query
            listen:     True if a user response is expected
        """
        LOG.info("Speak: " + utterance)
        try:
            self.tts.execute(utterance, ident, listen)
        except Exception as e:
            LOG.exception(f"TTS synth failed! {e}")
            if self._tts_hash != self._fallback_tts_hash:
                self.execute_fallback_tts(utterance, ident, listen)

    def _get_tts_fallback(self):
        """Lazily initializes the fallback TTS if needed."""
        if not self.fallback_tts:
            config = Configuration()
            engine = config.get('tts', {}).get("fallback_module", "mimic")
            cfg = {"tts": {"module": engine,
                           engine: config.get('tts', {}).get(engine, {})}}
            self.fallback_tts = TTSFactory.create(cfg)
            self.fallback_tts.validator.validate()
            self.fallback_tts.init(self.bus)

        return self.fallback_tts

    def execute_fallback_tts(self, utterance, ident, listen):
        """Speak utterance using fallback TTS if connection is lost.

        Args:
            utterance (str): sentence to speak
            ident (str): interaction id for metrics
            listen (bool): True if interaction should end with mycroft listening
        """
        try:
            self.tts = self._get_tts_fallback()
            LOG.debug("TTS fallback, utterance : " + str(utterance))
            self.tts.execute(utterance, ident, listen)
            return
        except Exception as e:
            LOG.error(e)
            LOG.exception(f"TTS FAILURE! utterance : {utterance}")

    def handle_stop(self, message):
        """Handle stop message.

        Shutdown any speech.
        """
        if check_for_signal("isSpeaking", -1):
            self._last_stop_signal = time.time()
            self.tts.playback.clear()  # Clear here to get instant stop
            self.bus.emit(Message("mycroft.stop.handled", {"by": "TTS"}))

    def shutdown(self):
        """Shutdown the audio service cleanly.

        Stop any playing audio and make sure threads are joined correctly.
        """
        self.status.set_stopping()
        if self.tts.playback:
            self.tts.playback.shutdown()
            self.tts.playback.join()
        self.audio.shutdown()

    def init_messagebus(self):
        """
        Start speech related handlers.
        """
        Configuration.set_config_update_handlers(self.bus)
        self.bus.on('mycroft.stop', self.handle_stop)
        self.bus.on('mycroft.audio.speech.stop', self.handle_stop)
        self.bus.on('speak', self.handle_speak)
