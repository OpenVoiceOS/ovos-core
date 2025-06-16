from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestLangDisambiguation(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.minicroft = get_minicroft([])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_stt_lang(self):
        session = Session("123")
        session.lang = "en-US"
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "stt_lang": "ca-ES", # lang detection from audio plugin
            "request_lang": "pt-PT",  # lang tagged in source message (wake word config)
            "detected_lang": "nl-NL"  # lang detection from utterance (text) plugin
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = list(lang_keys.values())
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["stt_lang"]}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()


    def test_lang_text_detection(self):
        session = Session("123")
        session.lang = "en-US"
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "detected_lang": "nl-NL"  # lang detection from utterance (text) plugin
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = list(lang_keys.values())
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["detected_lang"]}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()

    def test_metadata_preferred_over_text_detection(self):
        session = Session("123")
        session.lang = "en-US"
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "request_lang": "pt-PT",  # lang tagged in source message (wake word config)
            "detected_lang": "nl-NL"  # lang detection from utterance (text) plugin
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = list(lang_keys.values())
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["request_lang"]}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()

    def test_invalid_lang_detection(self):
        session = Session("123")
        session.lang = "en-US"
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "detected_lang": "nl-NL"
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = [session.lang]  # no nl-NL
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": session.lang}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()
