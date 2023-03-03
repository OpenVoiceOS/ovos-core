import time
from threading import Thread, Lock
from os.path import exists, expanduser
from mycroft_bus_client import Message

from mycroft.audio.tts import TTSFactory, TTS
from ovos_config.config import Configuration
from mycroft.metrics import report_timing, Stopwatch
from mycroft.audio.audioservice import AudioService
from mycroft.util import start_message_bus_client
from ovos_utils.signal import check_for_signal
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_plugin_manager.tts import get_tts_supported_langs, get_tts_lang_configs, get_tts_module_configs
from ovos_plugin_manager.audio import get_audio_service_configs
from ovos_plugin_manager.g2p import get_g2p_lang_configs, get_g2p_supported_langs, get_g2p_module_configs


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


class PlaybackService(Thread):
    def __init__(self, ready_hook=on_ready, error_hook=on_error,
                 stopping_hook=on_stopping, alive_hook=on_alive,
                 started_hook=on_started, watchdog=lambda: None, bus=None):
        super(PlaybackService, self).__init__()

        LOG.info("Starting Audio Service")
        callbacks = StatusCallbackMap(on_ready=ready_hook, on_error=error_hook,
                                      on_stopping=stopping_hook,
                                      on_alive=alive_hook,
                                      on_started=started_hook)
        self.status = ProcessStatus('audio', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration()
        self.native_sources = self.config["Audio"].get("native_sources",
                                                       ["debug_cli", "audio"]) or []
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

    @staticmethod
    def get_tts_lang_options(lang, blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"engine": "ovos-tts-plugin-mimic3",
          "offline": True,
          "lang": "en-us",
          "gender": "male",
          "voice": "ap",
          "display_name": "Alan Pope",
          "plugin_name": 'OVOS TTS Plugin Mimic3'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_tts_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for voice in configs:
                voice["plugin_name"] = plugin_display_name
                voice["engine"] = engine
                voice["lang"] = voice.get("lang") or lang
                opts.append(voice)
        return opts

    @staticmethod
    def get_g2p_lang_options(lang, blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"engine": "ovos-g2p-plugin-mimic",
          "offline": True,
          "lang": "en-us",
          "native_alphabet": "ARPA",
          "display_name": "Mimic G2P",
          "plugin_name": 'OVOS G2P Plugin Mimic'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_g2p_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for voice in configs:
                voice["plugin_name"] = plugin_display_name
                voice["engine"] = engine
                voice["lang"] = voice.get("lang") or lang
                opts.append(voice)
        return opts

    @staticmethod
    def get_audio_options(blacklist=None):
        """ returns a list of options to be consumed by an external UI
        each dict contains metadata about the plugins

        eg:
          [{"type": "ovos_common_play",
          "active": True,
          "plugin_name": 'Ovos Common Play'}]
        """
        blacklist = blacklist or []
        opts = []
        cfgs = get_audio_service_configs()
        for name, config in cfgs.items():
            engine = config["type"]
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            config["plugin_name"] = plugin_display_name
            opts.append(config)
        return opts

    def handle_opm_tts_query(self, message):
        """ Responds to opm.tts.query with data about installed plugins

        Response message.data will contain:
        "langs" - list of supported languages
        "plugins" - {lang: [list_of_plugins]}
        "configs" - {plugin_name: {lang: [list_of_valid_configs]}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        plugs = get_tts_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_tts_module_configs(p)
            opts[lang] = self.get_tts_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    def handle_opm_g2p_query(self, message):
        """ Responds to opm.g2p.query with data about installed plugins

        Response message.data will contain:
        "langs" - list of supported languages
        "plugins" - {lang: [list_of_plugins]}
        "configs" - {plugin_name: {lang: [list_of_valid_configs]}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        plugs = get_g2p_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_g2p_module_configs(p)
            opts[lang] = self.get_g2p_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    def handle_opm_audio_query(self, message):
        """ Responds to opm.audio.query with data about installed plugins

        Response message.data will contain:
        "plugins" - [list_of_plugins]
        "configs" - {backend_name: backend_cfg}}
        "options" - {lang: [list_of_valid_ui_metadata]}
        """
        cfgs = get_audio_service_configs()
        data = {
            "plugins": list(cfgs.keys()),
            "configs": cfgs,
            "options": self.get_audio_options()
        }
        self.bus.emit(message.response(data))

    def run(self):
        self.status.set_alive()
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
                any(s in message.context['destination'] for s in self.native_sources):
            return

        # Get conversation ID
        if message.context and 'ident' in message.context:
            ident = message.context['ident']
        else:
            ident = 'unknown'

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
            with self.lock:
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
            with self.lock:
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
        with self.lock:
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
            tts = self._get_tts_fallback()
            LOG.debug("TTS fallback, utterance : " + str(utterance))
            tts.execute(utterance, ident, listen)
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

    def handle_queue_audio(self, message):
        """ Queue a sound file to play in speech thread
         ensures it doesnt play over TTS """
        viseme = message.data.get("viseme")
        ident = message.data.get("ident") or message.context.get("ident")  # unused ?
        audio_ext = message.data.get("audio_ext")  # unused ?
        audio_file = message.data.get("filename")
        if not audio_file:
            raise ValueError(f"'filename' missing from message.data: {message.data}")
        audio_file = expanduser(audio_file)
        if not exists(audio_file):
            raise FileNotFoundError(f"{audio_file} does not exist")
        audio_ext = audio_ext or audio_file.split(".")[-1]
        listen = message.data.get("listen", False)
        TTS.queue.put((audio_ext, str(audio_file), viseme, ident, listen))

    def handle_get_languages_tts(self, message):
        """
        Handle a request for supported TTS languages
        :param message: ovos.languages.tts request
        """
        tts_langs = self.tts.available_languages or \
            [self.config.get('lang') or 'en-us']
        LOG.debug(f"Got tts_langs: {tts_langs}")
        self.bus.emit(message.response({'langs': list(tts_langs)}))

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
        self.bus.on('mycroft.audio.queue', self.handle_queue_audio)
        self.bus.on('speak', self.handle_speak)
        self.bus.on('ovos.languages.tts', self.handle_get_languages_tts)
        self.bus.on("opm.tts.query", self.handle_opm_tts_query)
        self.bus.on("opm.audio.query", self.handle_opm_audio_query)
        self.bus.on("opm.g2p.query", self.handle_opm_g2p_query)
