import unittest
from mycroft.skills.intent_services.padatious_service import PadatiousService, FallbackIntentContainer
from mycroft_bus_client.message import Message
from ovos_utils.messagebus import FakeBus


class UtteranceIntentMatchingTest(unittest.TestCase):
    def get_service(self, regex_only=False, fuzz=True):
        intent_service = PadatiousService(FakeBus(),
                                          {"regex_only": regex_only,
                                           "intent_cache": "~/.local/share/mycroft/intent_cache",
                                           "train_delay": 1,
                                           "fuzz": fuzz,
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
        self.assertFalse(intent_service.is_regex_only)
        for container in intent_service.containers.values():
            self.assertFalse(isinstance(container, FallbackIntentContainer))

        # exact match
        intent = intent_service.calc_intent("this is a test", "en-US")
        self.assertEqual(intent.name, "test")

        # fuzzy match
        intent = intent_service.calc_intent("this test", "en-US")
        self.assertEqual(intent.name, "test")
        self.assertTrue(intent.conf <= 0.8)

        # regex match
        intent = intent_service.calc_intent("tell me about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

        # fuzzy regex match - success
        intent = intent_service.calc_intent("tell me everything about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        # TODO - why are extracted entities lower case ???
        # i think case depends on padaos vs padatious matching internally
        # padaos (exact matches only) -> keep case
        # padatious -> lower case
        self.assertEqual(intent.matches, {'thing': 'mycroft'})
        self.assertTrue(intent.conf <= 0.9)

    def test_regex_intent(self):
        intent_service = self.get_service(regex_only=True, fuzz=False)

        # assert padacioso is loaded not padatious
        self.assertTrue(intent_service.is_regex_only)
        for container in intent_service.containers.values():
            self.assertTrue(isinstance(container, FallbackIntentContainer))

        # exact match
        intent = intent_service.calc_intent("this is a test", "en-US")
        self.assertEqual(intent.name, "test")

        # regex match
        intent = intent_service.calc_intent("tell me about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

        # fuzzy match - failure case (no fuzz)
        intent = intent_service.calc_intent("this is test", "en-US")
        self.assertTrue(intent.name is None)

        # fuzzy regex match - failure case (no fuzz)
        intent = intent_service.calc_intent("tell me everything about Mycroft", "en-US")
        self.assertTrue(intent.name is None)

    def test_regex_fuzz_intent(self):
        intent_service = self.get_service(regex_only=True, fuzz=True)

        # fuzzy match - success
        intent = intent_service.calc_intent("this is test", "en-US")
        self.assertEqual(intent.name, "test")
        self.assertTrue(intent.conf <= 0.8)

        # fuzzy regex match - success
        intent = intent_service.calc_intent("tell me everything about Mycroft", "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})
        self.assertTrue(intent.conf <= 0.8)


