import json
import os
import tempfile
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_config.config import Configuration
from ovos_config.models import LocalConf
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft


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
        # its current entry-point name, prepend it to
        # ``Configuration.xdg_configs``, and boot MiniCroft with
        # ``isolate_config=False`` so the boot-time
        # ``Configuration.reload()`` does not wipe the override.
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
        self.minicroft = get_minicroft(
            [self.skill_id], isolate_config=False)

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        Configuration.xdg_configs = self._orig_xdg
        Configuration.reload()
        os.unlink(self._tmp_conf)
        LOG.set_level("CRITICAL")

    def test_cancel_match(self):
        session = Session("123")
        session.lang = "en-US"
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["can you tell me the...ummm...oh, nevermind that"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        # utterance cancelled -> no complete_intent_failure
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            final_session=session,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/cancel.mp3"}),
                Message("ovos.utterance.cancelled", {}),
                Message("ovos.utterance.handled", {}),

            ]
        )

        test.execute(timeout=10)

        # ensure hello world doesnt match either
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world cancel command"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/cancel.mp3"}),
                Message("ovos.utterance.cancelled", {}),
                Message("ovos.utterance.handled", {}),

            ]
        )

        test.execute(timeout=10)
