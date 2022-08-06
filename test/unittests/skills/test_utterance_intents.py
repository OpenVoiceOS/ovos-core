import unittest

from adapt.intent import IntentBuilder
from mycroft.skills.intent_service_interface import IntentServiceInterface
from mycroft.skills.intent_services.padatious_service import PadatiousService, FallbackIntentContainer
from mycroft_bus_client.message import Message
from ovos_utils.messagebus import FakeBus


class UtteranceIntentMatchingTest(unittest.TestCase):
    def get_service(self, regex_only=False):
        intent_service = PadatiousService(FakeBus(),
                                          {"regex_only": regex_only,
                                           "intent_cache": "~/.local/share/mycroft/intent_cache",
                                           "train_delay": 1,
                                           "single_thread": True,
                                           })
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
        intent_service.train()

        return intent_service

    def test_padatious_intent(self):
        intent_service = self.get_service()

        # assert padatious is loaded not padacioso
        self.assertFalse(intent_service._regex_only)
        for container in intent_service.containers.values():
            self.assertFalse(isinstance(container, FallbackIntentContainer))

        # exact match
        intent = intent_service.calc_intent("this is a test", "en-US")
        self.assertEqual(intent.name, "test")

        # regex match
        intent = intent_service.calc_intent("tell me about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

    def test_regex_intent(self):
        intent_service = self.get_service(regex_only=True)

        # assert padacioso is loaded not padatious
        self.assertTrue(intent_service._regex_only)
        for container in intent_service.containers.values():
            self.assertTrue(isinstance(container, FallbackIntentContainer))

        # exact match
        intent = intent_service.calc_intent("this is a test", "en-US")
        self.assertEqual(intent.name, "test")

        # regex match
        intent = intent_service.calc_intent("tell me about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

