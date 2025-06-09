from unittest import TestCase

from ovos_bus_client.message import Message

from ovoscope import End2EndTest, get_minicroft


class TestNoSkills(TestCase):

    def setUp(self):
        self.minicroft = get_minicroft([])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()

    def test_complete_failure(self):
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"]})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()

    def test_routing(self):
        # this test will validate source and destination are handled properly
        # done automatically if "source" and "destination" are in message.context
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"]},
                          {"source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()
