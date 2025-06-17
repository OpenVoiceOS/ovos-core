from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft


class TestCancelIntentMidSentence(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
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

