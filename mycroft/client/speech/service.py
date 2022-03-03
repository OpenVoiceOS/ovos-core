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

from mycroft import dialog
from mycroft.client.speech.listener import RecognizerLoop
from mycroft.configuration import Configuration
from mycroft.enclosure.api import EnclosureAPI
from mycroft.identity import IdentityManager
from mycroft.messagebus.message import Message
from mycroft.util import (
    start_message_bus_client
)
from mycroft.util.log import LOG
from mycroft.util.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.file_utils import read_vocab_file, resolve_resource_file


def on_ready():
    LOG.info('Speech client is ready.')


def on_stopping():
    LOG.info('Speech service is shutting down...')


def on_error(e='Unknown'):
    LOG.error('Audio service failed to launch ({}).'.format(repr(e)))


class SpeechClient(Thread):
    def __init__(self, on_ready=on_ready, on_error=on_error,
                 on_stopping=on_stopping, watchdog=lambda: None):
        super(SpeechClient, self).__init__()

        callbacks = StatusCallbackMap(on_ready=on_ready,
                                      on_error=on_error,
                                      on_stopping=on_stopping)
        self.status = ProcessStatus('speech', callback_map=callbacks)
        self.status.set_started()

        self.config = Configuration.get()
        self.bus = start_message_bus_client("VOICE")
        self.connect_bus_events()
        self.status.bind(self.bus)

        # Register handlers on internal RecognizerLoop bus
        self.loop = RecognizerLoop(self.bus, watchdog)
        self.connect_loop_events()

    # loop events
    def handle_record_begin(self):
        """Forward internal bus message to external bus."""
        LOG.info("Begin Recording...")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('recognizer_loop:record_begin', context=context))

    def handle_record_end(self):
        """Forward internal bus message to external bus."""
        LOG.info("End Recording...")
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('recognizer_loop:record_end', context=context))

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
        LOG.info("Wakeword Detected: " + event['utterance'])
        self.bus.emit(Message('recognizer_loop:wakeword', event))

    def handle_hotword(self, event):
        LOG.info("Hotword Detected: " + event['hotword'])
        self.bus.emit(Message('recognizer_loop:hotword', event))

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

    # messagebus events
    def handle_complete_intent_failure(self, message):
        """Extreme backup for answering completely unhandled intent requests."""
        LOG.info("Failed to find intent.")
        data = {'utterance': dialog.get('not.loaded')}
        context = {'client_name': 'mycroft_listener',
                   'source': 'audio'}
        self.bus.emit(Message('speak', data, context))

    def handle_sleep(self, message):
        """Put the recognizer loop to sleep."""
        self.loop.sleep()

    def handle_wake_up(self, message):
        """Wake up the the recognize loop."""
        self.loop.awaken()

    def handle_mic_mute(self, message):
        """Mute the listener system."""
        self.loop.mute()

    def handle_mic_unmute(self, message):
        """Unmute the listener system."""
        self.loop.unmute()

    def handle_mic_listen(self, message):
        """Handler for mycroft.mic.listen.

        Starts listening as if wakeword was spoken.
        """
        self.loop.responsive_recognizer.trigger_listen()

    def handle_mic_get_status(self, message):
        """Query microphone mute status."""
        data = {'muted': self.loop.is_muted()}
        self.bus.emit(message.response(data))

    def handle_paired(self, message):
        """Update identity information with pairing data.

        This is done here to make sure it's only done in a single place.
        TODO: Is there a reason this isn't done directly in the pairing skill?
        """
        IdentityManager.update(message.data)

    def handle_audio_start(self, message):
        """Mute recognizer loop."""
        if self.config.get("listener").get("mute_during_output"):
            self.loop.mute()

    def handle_audio_end(self, message):
        """Request unmute, if more sources have requested the mic to be muted
        it will remain muted.
        """
        if self.config.get("listener").get("mute_during_output"):
            self.loop.unmute()  # restore

    def handle_stop(self, message):
        """Handler for mycroft.stop, i.e. button press."""
        self.loop.force_unmute()

    # stt control bus events
    def handle_load_stt_lang(self, message):
        """ tell STT to pre load a model for this language, it will be needed """
        lang = message.data.get("lang") or Configuration.get().get("lang", "en-us")
        LOG.info(f"Loading STT lang: {lang}")
        if hasattr(self.loop.stt, "load_language"):
            try:
                self.loop.stt.load_language(lang)
            except:
                LOG.exception(f"Failed to load STT lang: {lang}")
        if hasattr(self.loop.fallback_stt, "load_language"):
            try:
                self.loop.fallback_stt.load_language(lang)
            except:
                LOG.exception(f"Failed to load fallback STT lang: {lang}")

    def handle_unload_stt_lang(self, message):
        """ tell STT to unload model for this language, it won't be needed anymore """
        lang = message.data.get("lang") or Configuration.get().get("lang", "en-us")
        LOG.info(f"Unloading STT lang: {lang}")
        if hasattr(self.loop.stt, "unload_language"):
            try:
                self.loop.stt.unload_language(lang)
            except:
                LOG.exception(f"Failed to unload STT lang: {lang}")
        if hasattr(self.loop.fallback_stt, "unload_language"):
            try:
                self.loop.fallback_stt.unload_language(lang)
            except:
                LOG.exception(f"Failed to unload fallback STT lang: {lang}")

    def handle_enable_limited_vocab(self, message):
        """ enable limited vocabulary mode if supported
        will only consider pre defined .voc files

        message.data optional parameters:

        lang (str): default to system lang
        top_words (bool): default True, augment vocab with 10k most common words for lang
        permanent (bool): default False, tell STT if it should
            expect to stay in limited voc mode permanently or if it is temporary,
            engines might unload models from memory based on this
        english_fallback (bool): default False, use en res files if lang file not found
        samples (list): list of strings with extra vocabulary to enable
        vocabs (list): list of strings with name of .voc file resources to enable
        intents (list): list of strings with name of .intent file resources to enable
        entities (list): list of strings with name of .entity file resources to enable
        dialogs (list): list of strings with name of .dialog file resources to enable

        NOTE: resource files are located via resolve_resource_file(f"text/{lang}/{voc_file}.{ext}")
        """
        lang = message.data.get("lang") or Configuration.get().get("lang", "en-us")
        fallback = message.data.get("english_fallback", False)
        permanent = message.data.get("permanent", False)
        top_words = message.data.get("top_words", True)

        # samples defined in message.data
        words = ["[unk]"] + \
                message.data.get("samples", [])

        def read_file(voc_file, ext):
            voc = resolve_resource_file(f"text/{lang}/{voc_file}.{ext}") or \
                  resolve_resource_file(f"locale/{lang}/{voc_file}.{ext}")
            if lang != "en-us" and not voc and fallback:
                voc = resolve_resource_file(f"text/en-us/{voc_file}.{ext}") or \
                      resolve_resource_file(f"locale/en-us/{voc_file}.{ext}")
            if voc:
                return [item for sublist in read_vocab_file(voc) for item in sublist]
            return []

        # read voc files
        if top_words:
            # most common 10k words for language
            words += read_file("limited_stt", "voc")
        for voc_file in message.data.get("vocabs", []):
            # user defined voc files to load
            words += read_file(voc_file, "voc")
        for voc_file in message.data.get("dialogs", []):
            # user defined dialog files to load
            words += read_file(voc_file, "dialog")
        for voc_file in message.data.get("intents", []):
            # user defined intent files to load
            words += read_file(voc_file, "intent")
        for voc_file in message.data.get("entities", []):
            # user defined entity files to load
            words += read_file(voc_file, "entity")

        LOG.info(f"Enabling limited vocab:  {words}")
        if hasattr(self.loop.stt, "enable_limited_vocabulary"):
            try:
                self.loop.stt.enable_limited_vocabulary(words,
                                                        lang=lang,
                                                        permanent=permanent)
            except:
                LOG.exception(f"Failed to enable limited STT vocabulary")
        if hasattr(self.loop.fallback_stt, "enable_limited_vocabulary"):
            try:
                self.loop.fallback_stt.enable_limited_vocabulary(words,
                                                    lang=lang,
                                                    permanent=permanent)
            except:
                LOG.exception(f"Failed to enable limited fallback STT vocabulary")

    def handle_enable_full_vocab(self, message):
        """ re enable default transcription mode """
        lang = message.data.get("lang") or Configuration.get().get("lang", "en-us")
        LOG.info(f"Enabling full vocab: {lang}")
        if hasattr(self.loop.stt, "enable_full_vocabulary"):
            try:
                self.loop.stt.enable_full_vocabulary(lang)
            except:
                LOG.exception(f"Failed to disable limited STT vocabulary")
        if hasattr(self.loop.fallback_stt, "enable_full_vocabulary"):
            try:
                self.loop.fallback_stt.enable_full_vocabulary(lang)
            except:
                LOG.exception(f"Failed to disable limited fallback STT vocabulary")

    def handle_enable_yesno_vocab(self, message):
        """ enable limited vocabulary mode if supported
        will only consider yes / no answer variations
        """
        message.data["vocabs"] = ["yes", "no"]
        message.data["english_fallback"] = True
        message.data["permanent"] = False
        message.data["top_words"] = False
        self.handle_enable_limited_vocab(message)

    # loop initialization
    def handle_open(self):
        # TODO: Move this into the Enclosure (not speech client)
        # Reset the UI to indicate ready for speech processing
        EnclosureAPI(self.bus).reset()

    def connect_loop_events(self):
        self.loop.on('recognizer_loop:utterance', self.handle_utterance)
        self.loop.on('recognizer_loop:speech.recognition.unknown',
                     self.handle_unknown)
        self.loop.on('speak', self.handle_speak)
        self.loop.on('recognizer_loop:record_begin', self.handle_record_begin)
        self.loop.on('recognizer_loop:awoken', self.handle_awoken)
        self.loop.on('recognizer_loop:wakeword', self.handle_wakeword)
        self.loop.on('recognizer_loop:hotword', self.handle_hotword)
        self.loop.on('recognizer_loop:record_end', self.handle_record_end)
        self.loop.on('recognizer_loop:no_internet', self.handle_no_internet)
        self.loop.on('recognizer_loop:hotword_event',
                     self.handle_hotword_event)

    def connect_bus_events(self):
        # Register handlers for events on main Mycroft messagebus
        self.bus.on('open', self.handle_open)
        self.bus.on('complete_intent_failure',
                    self.handle_complete_intent_failure)
        self.bus.on('recognizer_loop:sleep', self.handle_sleep)
        self.bus.on('recognizer_loop:wake_up', self.handle_wake_up)
        self.bus.on('mycroft.mic.mute', self.handle_mic_mute)
        self.bus.on('mycroft.mic.unmute', self.handle_mic_unmute)
        self.bus.on('mycroft.mic.get_status', self.handle_mic_get_status)
        self.bus.on('mycroft.mic.listen', self.handle_mic_listen)
        self.bus.on("mycroft.paired", self.handle_paired)
        self.bus.on('recognizer_loop:audio_output_start',
                    self.handle_audio_start)
        self.bus.on('recognizer_loop:audio_output_end', self.handle_audio_end)
        self.bus.on('recognizer_loop:load_language', self.handle_load_stt_lang)
        self.bus.on('recognizer_loop:unload_language', self.handle_unload_stt_lang)
        self.bus.on('recognizer_loop:set_yesno_vocab', self.handle_enable_yesno_vocab)
        self.bus.on('recognizer_loop:set_limited_vocab', self.handle_enable_limited_vocab)
        self.bus.on('recognizer_loop:set_full_vocab', self.handle_enable_full_vocab)
        self.bus.on('mycroft.stop', self.handle_stop)

    def run(self):
        self.status.set_started()
        try:
            self.status.set_ready()
            self.loop.run()
        except Exception as e:
            self.status.set_error(e)
        self.status.set_stopping()

