from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestNoSkills(TestCase):

    def setUp(self):
        """
        Sets up the test environment before each test.
        
        Initializes logging to DEBUG level and creates a minicroft instance with no skills loaded for use in tests.
        """
        LOG.set_level("DEBUG")
        self.minicroft = get_minicroft([])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        """
        Cleans up after each test by stopping the minicroft instance and resetting logging level to CRITICAL.
        """
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_complete_failure(self):
        """
        Tests system behavior when no skills are loaded and an utterance is received.
        
        Verifies that the system responds to an unhandled utterance by playing an error sound, emitting a complete intent failure message, and marking the utterance as handled.
        """
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
        """
        Tests that message routing with 'source' and 'destination' context fields is handled correctly when no skills are loaded.
        
        Verifies that the system produces the expected sequence of messages, including correct propagation of routing context, when processing an utterance event.
        """
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
