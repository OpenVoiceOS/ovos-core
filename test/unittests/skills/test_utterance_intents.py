import unittest
from mycroft.skills.intent_services.padatious_service import PadatiousService, FallbackIntentContainer
from ovos_bus_client.message import Message
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
        try:
            import padatious
            self.assertFalse(intent_service.is_regex_only)
            self.assertFalse(intent_service.threaded_inference)
            for container in intent_service.containers.values():
                self.assertNotIsInstance(container, FallbackIntentContainer)
        except ImportError:
            self.assertTrue(intent_service.is_regex_only)
            self.assertFalse(intent_service.threaded_inference)
            for container in intent_service.containers.values():
                self.assertIsInstance(container, FallbackIntentContainer)

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
        utterance = "tell me everything about Mycroft"
        intent = intent_service.calc_intent(utterance, "en-US")
        self.assertEqual(intent.name, "test2")

        # case depends on padaos vs padatious matching internally
        # padaos (exact matches only) -> keep case
        # padacioso -> keep case
        # padatious -> lower case
        if intent_service.is_regex_only:
            self.assertEqual(intent.matches, {'thing': 'Mycroft'})
            self.assertEqual(intent.sent, utterance)
        else:
            self.assertEqual(intent.matches, {'thing': 'mycroft'})
            self.assertEqual(intent.sent, utterance)
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
        utterance = "tell me about Mycroft"
        intent = intent_service.calc_intent(utterance, "en-US")
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft'})

        # fuzzy match - failure case (no fuzz)
        intent = intent_service.calc_intent("this is test", "en-US")
        self.assertTrue(intent.name is None)

        # fuzzy regex match - failure case (no fuzz)
        intent = intent_service.calc_intent("tell me everything about Mycroft",
                                            "en-US")
        self.assertTrue(intent.name is None)

    def test_regex_fuzz_intent(self):
        intent_service = self.get_service(regex_only=True, fuzz=True)

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

    def test_threaded_intent(self):
        from time import time
        intent_service = self.get_service(regex_only=True, fuzz=False)
        utterances = []
        for i in range(50):
            utterances.append("tell me about Mycroft")
        intent_service.padatious_config['threaded_inference'] = False
        start = time()
        intent = intent_service.threaded_calc_intent(utterances, "en-US")
        single_thread_time = time() - start
        self.assertEqual(intent.name, "test2")
        self.assertEqual(intent.matches, {'thing': 'Mycroft',
                                          'utterance': utterances[0]})
        self.assertEqual(intent.sent, utterances[0])

        intent_service.padatious_config['threaded_inference'] = True
        start = time()
        intent2 = intent_service.threaded_calc_intent(utterances, "en-US")
        multi_thread_time = time() - start
        self.assertEqual(intent.__dict__, intent2.__dict__)

        speedup = (single_thread_time - multi_thread_time) / len(utterances)
        print(f"speedup={speedup}")
        # Assert threaded execution was faster (or at least not much slower)
        self.assertGreaterEqual(speedup, -0.01)
