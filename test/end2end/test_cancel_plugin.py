import json
import os
import tempfile
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_config.config import Configuration
from ovos_config.models import LocalConf
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft


# Topics come from the ovos-spec-tools SpecMessage enum (spec namespace); the
# legacy counterpart is derived via migration_counterpart, never hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value              # ovos.utterance.handle
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)  # recognizer_loop:utterance
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value      # ovos.utterance.handled
UTTERANCE_CANCELLED = SpecMessage.UTTERANCE_CANCELLED.value  # ovos.utterance.cancelled

# The two namespace paths the scenario is run on.
#   key       -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    # the only path left: the bridge is gone, so a legacy producer reaches
    # nothing (pinned in test_no_legacy_wire_compat.py)
    "spec": (False, False, SPEC_UTTERANCE),
}


# Entry-point name of the cancel transformer as it ships in
# ovos-utterance-plugin-cancel>=0.3.0a1. The OVOS default mycroft.conf
# still references the historic name ``ovos-utterance-plugin-cancel``
# under ``utterance_transformers``; UtteranceTransformersService loads
# a plugin only when its entry-point name is a key in that mapping
# (``ovos_core/transformers.py``), so the default config silently
# skips the new name. Patch in a temp config that enables the new key.
PLUGIN_NAME = "ovos-utterance-cancel-plugin"


class TestCancelIntentMidSentence(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        # Write a temp xdg-conf enabling the cancel transformer under
        # its current entry-point name and prepend it to
        # ``Configuration.xdg_configs``. MiniCroft is booted in the
        # per-namespace helper with ``isolate_config=False`` so the
        # boot-time ``Configuration.reload()`` does not wipe the override.
        cfg_data = {"utterance_transformers": {PLUGIN_NAME: {"active": True}}}
        fd, self._tmp_conf = tempfile.mkstemp(
            prefix="ovos-core-cancel-test-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg_data, fh)
        self._orig_xdg = Configuration.xdg_configs[:]
        Configuration.xdg_configs = (
            [LocalConf(self._tmp_conf)] + Configuration.xdg_configs)
        Configuration.reload()

        self.skill_id = "ovos-skill-hello-world.openvoiceos"

    def tearDown(self):
        Configuration.xdg_configs = self._orig_xdg
        Configuration.reload()
        os.unlink(self._tmp_conf)
        LOG.set_level("CRITICAL")

    def _run_cancel_match(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft(
            [self.skill_id], isolate_config=False,
            modernize=modernize, emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            message = Message(utt_topic,
                              {"utterances": ["can you tell me the...ummm...oh, nevermind that"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            # utterance cancelled -> no complete_intent_failure
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[self.skill_id],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                source_message=message,
                final_session=session,
                expected_messages=[
                    message,
                    Message(SpecMessage.AUDIO_PLAY_SOUND, {"uri": "snd/cancel.mp3"}),
                    Message(UTTERANCE_CANCELLED, {}),
                    Message(UTTERANCE_HANDLED, {}),

                ]
            )

            test.execute(timeout=10)

            # ensure hello world doesnt match either
            message = Message(utt_topic,
                              {"utterances": ["hello world cancel command"], "lang": "en-US"},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[self.skill_id],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                source_message=message,
                expected_messages=[
                    message,
                    Message(SpecMessage.AUDIO_PLAY_SOUND, {"uri": "snd/cancel.mp3"}),
                    Message(UTTERANCE_CANCELLED, {}),
                    Message(UTTERANCE_HANDLED, {}),

                ]
            )

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_cancel_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_cancel_match(namespace)
