import unittest

from ovos_utils.messagebus import FakeBus

from ovos_bus_client.message import Message
from ovos_core.intent_services.padacioso_service import FallbackIntentContainer, PadaciosoService


class UtteranceIntentMatchingTest(unittest.TestCase):
    def get_service(self, fuzz=True):
        intent_service = PadaciosoService(FakeBus(), {"fuzz": fuzz})
        # register test intents
        filename = "/tmp/test.intent"
        with open(filename, "w") as f:
            f.write("this is a test\ntest the intent\nexecute test")
        rxfilename = "/tmp/test2.intent"
        with open(rxfilename, "w") as f:
            f.write("tell me about {thing}\nwhat is {thing}")
        data = {'file_name': filename, 'lang': 'en-US', 'name': 'test'}
        intent_service.register_intent(Message("padatious:register_intent", data))
        data = {'file_name': rxfilename, 'lang': 'en-US', 'name': 'test2'}
        intent_service.register_intent(Message("padatious:register_intent", data))
        return intent_service

    def test_padacioso_intent(self):
        intent_service = self.get_service(fuzz=False)

        for container in intent_service.containers.values():
            self.assertIsInstance(container, FallbackIntentContainer)

        # exact match
        intent = intent_service.calc_intent("this is a test", "en-US")
        self.assertEqual(intent.name, "test")

        # fuzzy match - failure case
        intent = intent_service.calc_intent("this test", "en-US")
        self.assertIsNone(intent)

        # regex match
        intent = intent_service.calc_intent("tell me about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

        # fuzzy regex match - failure case
        utterance = "tell me everything about Mycroft"
        intent = intent_service.calc_intent(utterance, "en-US")
        self.assertIsNone(intent)

    def test_padacioso_fuzz_intent(self):
        intent_service = self.get_service(fuzz=True)

        # fuzzy match - success
        intent = intent_service.calc_intent("this is test", "en-US")
        self.assertEqual(intent.name, "test")
        self.assertTrue(intent.conf <= 0.8)

        # fuzzy regex match - success
        utterance = "tell me everything about Mycroft"
        intent = intent_service.calc_intent(utterance, "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})
        self.assertEqual(intent.sent, utterance)
        self.assertTrue(intent.conf <= 0.8)
