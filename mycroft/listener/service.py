# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from threading import Thread

from mycroft.listener import RecognizerLoop
from mycroft.listener.mic import ListenerState, ListeningMode
from ovos_config.config import Configuration
from mycroft.enclosure.api import EnclosureAPI
from ovos_backend_client.identity import IdentityManager
from mycroft.messagebus.message import Message
from mycroft.util import (
    start_message_bus_client
)
from mycroft.util.log import LOG
from mycroft.util.process_utils import ProcessStatus, StatusCallbackMap
from ovos_plugin_manager.stt import get_stt_lang_configs, get_stt_supported_langs, get_stt_module_configs
from ovos_plugin_manager.wakewords import get_ww_lang_configs, get_ww_supported_langs, get_ww_module_configs
from ovos_plugin_manager.vad import get_vad_configs


def on_ready():
    LOG.info('Speech client is ready.')


def on_stopping():
    LOG.info('Speech service is shutting down...')


def on_error(e='Unknown'):
    LOG.error('Audio service failed to launch ({}).'.format(repr(e)))


class SpeechService(Thread):
    def __init__(self, on_ready=on_ready, on_error=on_error,
                 on_stopping=on_stopping, watchdog=lambda: None,
                 bus=None, loop=None):
        super(SpeechService, self).__init__()

        callbacks = StatusCallbackMap(on_ready=on_ready,
                                      on_error=on_error,
                                      on_stopping=on_stopping)
        self.status = ProcessStatus('speech', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration()
        self.bus = bus or start_message_bus_client("VOICE")

        self.status.bind(self.bus)

        # Register handlers on internal RecognizerLoop bus
        self.loop = loop or RecognizerLoop(self.bus, watchdog)
        self.connect_loop_events()
        self.connect_bus_events()

    # loop events
    def handle_record_begin(self):
        """Forward internal bus message to external bus."""
        LOG.info("Begin Recording...")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('recognizer_loop:record_begin', context=context))

    def handle_record_end(self, event):
        """Forward internal bus message to external bus."""
        LOG.info("End Recording...")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('recognizer_loop:record_end', event, context=context))

    def handle_no_internet(self):
        LOG.debug("Notifying enclosure of no internet connection")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('enclosure.notify.no_internet', context=context))

    def handle_awoken(self):
        """Forward mycroft.awoken to the messagebus."""
        LOG.info("Listener is now Awake: ")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('mycroft.awoken', context=context))

    def handle_wakeword(self, event):
        LOG.info("Wakeword Detected: " + event['hotword'])
        self.bus.emit(Message('recognizer_loop:wakeword', event))

    def handle_hotword(self, event):
        LOG.info("Hotword Detected: " + event['hotword'])
        self.bus.emit(Message('recognizer_loop:hotword', event))

    def handle_stopword(self, event):
        LOG.info("Stop word Detected: " + event['hotword'])
        self.bus.emit(Message('recognizer_loop:stopword', event))

    def handle_wakeupword(self, event):
        LOG.info("WakeUp word Detected: " + event['hotword'])
        self.bus.emit(Message('recognizer_loop:wakeupword', event))

    def handle_hotword_event(self, event):
        """ hotword configured to emit a bus event
        forward event from internal emitter to mycroft bus"""
        self.bus.emit(Message(event["msg_type"]))

    def handle_utterance(self, event):
        LOG.info("Utterance: " + str(event['utterances']))
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio',
                   'destination': ["skills"]}
        if 'ident' in event:
            ident = event.pop('ident')
            context['ident'] = ident
        self.bus.emit(Message('recognizer_loop:utterance', event, context))

    def handle_unknown(self):
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(
            Message('mycroft.speech.recognition.unknown', context=context))

    def handle_speak(self, event):
        """
            Forward speak message to message bus.
        """
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('speak', event, context))

    def handle_complete_intent_failure(self, event):
        """DEPRECATED - this handler is no longer called """

    def handle_change_state(self, event):
        """Set listening state."""
        state = event.data.get("state")
        mode = event.data.get("mode")
        needs_skip = self.loop.listen_state == ListenerState.WAKEWORD

        if state:
            if state == ListenerState.WAKEWORD:
                self.loop.listen_state = ListenerState.WAKEWORD
            elif state == ListenerState.CONTINUOUS:
                self.loop.listen_state = ListenerState.CONTINUOUS
            elif state == ListenerState.RECORDING:
                self.loop.listen_state = ListenerState.RECORDING
            else:
                LOG.error(f"Invalid listening state: {state}")

        if mode:
            if mode == ListeningMode.WAKEWORD:
                self.loop.listen_mode = ListeningMode.WAKEWORD
            elif mode == ListeningMode.CONTINUOUS:
                self.loop.listen_mode = ListeningMode.CONTINUOUS
            elif mode == ListeningMode.HYBRID:
                self.loop.listen_mode = ListeningMode.HYBRID
            else:
                LOG.error(f"Invalid listen mode: {mode}")

        # signal the recognizer to stop waiting for a wakeword
        # in order for it to enter the new state
        if needs_skip:
            self.loop.responsive_recognizer._listen_triggered = True

        self.handle_get_state(event)

    def handle_get_state(self, event):
        """Query listening state"""
        data = {'mode': self.loop.listen_mode,
                "state": self.loop.listen_state}
        self.bus.emit(event.reply("recognizer_loop:state", data))

    def handle_stop_recording(self, event):
        """Stop current recording session """
        self.loop.responsive_recognizer.stop_recording()

    def handle_extend_listening(self, event):
        """ when a skill is activated (converse) reset
        the timeout until wakeword is needed again
        only used when in hybrid listening mode """
        if self.loop.listen_mode == ListeningMode.HYBRID:
            self.loop.responsive_recognizer.extend_listening()

    def handle_sleep(self, event):
        """Put the recognizer loop to sleep."""
        self.loop.sleep()

    def handle_wake_up(self, event):
        """Wake up the the recognize loop."""
        self.loop.awaken()

    def handle_mic_mute(self, event):
        """Mute the listener system."""
        self.loop.mute()

    def handle_mic_unmute(self, event):
        """Unmute the listener system."""
        self.loop.unmute()

    def handle_mic_listen(self, _):
        """Handler for mycroft.mic.listen.

        Starts listening as if wakeword was spoken.
        """
        self.loop.responsive_recognizer.trigger_listen()

    def handle_mic_get_status(self, event):
        """Query microphone mute status."""
        data = {'muted': self.loop.is_muted()}
        self.bus.emit(event.response(data))

    def handle_paired(self, event):
        """Update identity information with pairing data.

        This is done here to make sure it's only done in a single place.
        TODO: Is there a reason this isn't done directly in the pairing skill?
        """
        IdentityManager.update(event.data)

    def handle_audio_start(self, event):
        """Mute recognizer loop."""
        if self.config.get("listener").get("mute_during_output"):
            self.loop.mute()

    def handle_audio_end(self, event):
        """Request unmute, if more sources have requested the mic to be muted
        it will remain muted.
        """
        if self.config.get("listener").get("mute_during_output"):
            self.loop.unmute()  # restore

    def handle_stop(self, event):
        """Handler for mycroft.stop, i.e. button press."""
        self.loop.force_unmute()

    def handle_open(self):
        # TODO: Move this into the Enclosure (not speech client)
        # Reset the UI to indicate ready for speech processing
        EnclosureAPI(self.bus).reset()

    def handle_get_languages_stt(self, message):
        """
        Handle a request for supported STT languages
        :param message: ovos.languages.stt request
        """
        stt_langs = self.loop.stt.available_languages or \
            [self.config.get('lang') or 'en-us']
        LOG.debug(f"Got stt_langs: {stt_langs}")
        self.bus.emit(message.response({'langs': list(stt_langs)}))

    @staticmethod
    def get_stt_lang_options(lang, blacklist=None):
        blacklist = blacklist or []
        opts = []
        cfgs = get_stt_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for config in configs:
                config["plugin_name"] = plugin_display_name
                config["engine"] = engine
                config["lang"] = config.get("lang") or lang
                opts.append(config)
        return opts

    @staticmethod
    def get_ww_lang_options(lang, blacklist=None):
        blacklist = blacklist or []
        opts = []
        cfgs = get_ww_lang_configs(lang=lang, include_dialects=True)
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for config in configs:
                config["plugin_name"] = plugin_display_name
                config["engine"] = engine
                config["lang"] = config.get("lang") or lang
                opts.append(config)
        return opts

    @staticmethod
    def get_vad_options(blacklist=None):
        blacklist = blacklist or []
        tts_opts = []
        cfgs = get_vad_configs()
        for engine, configs in cfgs.items():
            if engine in blacklist:
                continue
            # For Display purposes, we want to show the engine name without the underscore or dash and capitalized all
            plugin_display_name = engine.replace("_", " ").replace("-", " ").title()
            for voice in configs:
                voice["plugin_name"] = plugin_display_name
                voice["engine"] = engine
                tts_opts.append(voice)
        return tts_opts

    def handle_opm_stt_query(self, message):
        plugs = get_stt_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_stt_module_configs(p)
            opts[lang] = self.get_stt_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    def handle_opm_ww_query(self, message):
        plugs = get_ww_supported_langs()
        configs = {}
        opts = {}
        for lang, m in plugs.items():
            for p in m:
                configs[p] = get_ww_module_configs(p)
            opts[lang] = self.get_ww_lang_options(lang)

        data = {
            "plugins": plugs,
            "langs": list(plugs.keys()),
            "configs": configs,
            "options": opts
        }
        self.bus.emit(message.response(data))

    def handle_opm_vad_query(self, message):
        cfgs = get_vad_configs()
        data = {
            "plugins": list(cfgs.keys()),
            "configs": cfgs,
            "options": self.get_vad_options()
        }
        self.bus.emit(message.response(data))

    def connect_loop_events(self):
        self.loop.on('recognizer_loop:utterance', self.handle_utterance)
        self.loop.on('recognizer_loop:speech.recognition.unknown',
                     self.handle_unknown)
        self.loop.on('speak', self.handle_speak)
        self.loop.on('recognizer_loop:record_begin', self.handle_record_begin)
        self.loop.on('recognizer_loop:awoken', self.handle_awoken)
        self.loop.on('recognizer_loop:wakeword', self.handle_wakeword)
        self.loop.on('recognizer_loop:hotword', self.handle_hotword)
        self.loop.on('recognizer_loop:stopword', self.handle_stopword)
        self.loop.on('recognizer_loop:wakeupword', self.handle_wakeupword)
        self.loop.on('recognizer_loop:record_end', self.handle_record_end)
        self.loop.on('recognizer_loop:no_internet', self.handle_no_internet)
        self.loop.on('recognizer_loop:hotword_event',
                     self.handle_hotword_event)

    def connect_bus_events(self):
        # Register handlers for events on main Mycroft messagebus
        self.bus.on('open', self.handle_open)
        self.bus.on('recognizer_loop:sleep', self.handle_sleep)
        self.bus.on('recognizer_loop:wake_up', self.handle_wake_up)
        self.bus.on('recognizer_loop:record_stop', self.handle_stop_recording)
        self.bus.on('recognizer_loop:state.set', self.handle_change_state)
        self.bus.on('recognizer_loop:state.get', self.handle_get_state)
        self.bus.on('mycroft.mic.mute', self.handle_mic_mute)
        self.bus.on('mycroft.mic.unmute', self.handle_mic_unmute)
        self.bus.on('mycroft.mic.get_status', self.handle_mic_get_status)
        self.bus.on('mycroft.mic.listen', self.handle_mic_listen)
        self.bus.on("mycroft.paired", self.handle_paired)
        self.bus.on('recognizer_loop:audio_output_start',
                    self.handle_audio_start)
        self.bus.on('recognizer_loop:audio_output_end', self.handle_audio_end)
        self.bus.on('mycroft.stop', self.handle_stop)
        self.bus.on("ovos.languages.stt", self.handle_get_languages_stt)
        self.bus.on("intent.service.skills.activated", self.handle_extend_listening)
        self.bus.on("opm.stt.query", self.handle_opm_stt_query)
        self.bus.on("opm.ww.query", self.handle_opm_ww_query)
        self.bus.on("opm.vad.query", self.handle_opm_vad_query)

    def run(self):
        self.status.set_alive()
        try:
            self.status.set_ready()
            self.loop.run()
        except Exception as e:
            self.status.set_error(e)

        self.shutdown()

    def shutdown(self):
        self.status.set_stopping()
        self.loop.stop()


class SpeechClient(SpeechService):
    def __init__(self, *args, **kwargs):
        LOG.warning("SpeechClient has been renamed to SpeechService, it will be removed in 0.1.0")
        super().__init__(self, *args, **kwargs)

