"""End-to-end tests for language disambiguation, exercised on BOTH bus namespaces.

- **spec**: ``modernize=False, emit_legacy=False`` — utterance injected on the spec
  topic ``ovos.utterance.handle``; core handles it natively, no bridging.
- **legacy**: ``modernize=True, emit_legacy=False`` — utterance injected on the
  legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the spec listener handles it.

The lang-detection context keys (stt_lang, request_lang, detected_lang,
valid_langs) are preserved exactly on both paths; only message[0]'s topic differs.
"""
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# key -> (modernize, emit_legacy, utterance_topic)
# Topics from the ovos-spec-tools SpecMessage enum; legacy derived, not hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
SPEC_SPEAK = SpecMessage.SPEAK.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value

NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestLangDisambiguation(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_stt_lang(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        message = Message(utt_topic,
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
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["stt_lang"]}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_stt_lang(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stt_lang(namespace)

    def _run_lang_text_detection(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        message = Message(utt_topic,
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "detected_lang": "nl-NL"  # lang detection from utterance (text) plugin
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = list(lang_keys.values())
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["detected_lang"]}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_lang_text_detection(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_lang_text_detection(namespace)

    def _run_metadata_preferred_over_text_detection(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        message = Message(utt_topic,
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "request_lang": "pt-PT",  # lang tagged in source message (wake word config)
            "detected_lang": "nl-NL"  # lang detection from utterance (text) plugin
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = list(lang_keys.values())
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": lang_keys["request_lang"]}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_metadata_preferred_over_text_detection(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_metadata_preferred_over_text_detection(namespace)

    def _run_invalid_lang_detection(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        message = Message(utt_topic,
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize()})
        lang_keys = {
            "detected_lang": "nl-NL"
        }
        message.context.update(lang_keys)
        message.context["valid_langs"] = [session.lang]  # no nl-NL
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {"lang": session.lang}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_invalid_lang_detection(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_invalid_lang_detection(namespace)
