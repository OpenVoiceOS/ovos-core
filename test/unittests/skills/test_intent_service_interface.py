import unittest

from adapt.intent import IntentBuilder
from mycroft.skills.intent_service_interface import IntentServiceInterface


class MockEmitter:
    def __init__(self):
        self.reset()

    def emit(self, message):
        self.types.append(message.msg_type)
        self.results.append(message.data)

    def get_types(self):
        return self.types

    def get_results(self):
        return self.results

    def on(self, event, f):
        pass

    def reset(self):
        self.types = []
        self.results = []


class KeywordRegistrationTest(unittest.TestCase):
    def check_emitter(self, expected_message_data):
        """Verify that the registration messages matches the expected."""
        for msg_type in self.emitter.get_types():
            self.assertEqual(msg_type, 'register_vocab')
        self.assertEqual(
            sorted(self.emitter.get_results(),
                   key=lambda d: sorted(d.items())),
            sorted(expected_message_data, key=lambda d: sorted(d.items())))
        self.emitter.reset()

    def setUp(self):
        self.emitter = MockEmitter()

    def test_register_keyword(self):
        intent_service = IntentServiceInterface(self.emitter)
        intent_service.register_adapt_keyword('test_intent', 'test', lang='en-US')
        entity_data = {'entity_value': 'test', 'entity_type': 'test_intent', 'lang': 'en-US'}
        compatibility_data = {'start': 'test', 'end': 'test_intent'}
        expected_data = {**entity_data, **compatibility_data}
        self.check_emitter([expected_data])

    def test_register_keyword_with_aliases(self):
        # TODO 22.02: Remove compatibility data
        intent_service = IntentServiceInterface(self.emitter)
        intent_service.register_adapt_keyword('test_intent', 'test',
                                              ['test2', 'test3'],
                                              lang='en-US')

        entity_data = {'entity_value': 'test', 'entity_type': 'test_intent', 'lang': 'en-US'}
        compatibility_data = {'start': 'test', 'end': 'test_intent'}
        expected_initial_vocab = {**entity_data, **compatibility_data}

        alias_data = {
            'entity_value': 'test2',
            'entity_type': 'test_intent',
            'alias_of': 'test',
            'lang': 'en-US'
        }
        alias_compatibility = {'start': 'test2', 'end': 'test_intent'}
        expected_alias1 = {**alias_data, **alias_compatibility}

        alias_data2 = {
            'entity_value': 'test3',
            'entity_type': 'test_intent',
            'alias_of': 'test',
            'lang': 'en-US'
        }
        alias_compatibility2 = {'start': 'test3', 'end': 'test_intent'}
        expected_alias2 = {**alias_data2, **alias_compatibility2}

        self.check_emitter([expected_initial_vocab,
                            expected_alias1,
                            expected_alias2])

    def test_register_regex(self):
        intent_service = IntentServiceInterface(self.emitter)
        intent_service.register_adapt_regex('.*', lang="en-us")
        self.check_emitter([{'regex': '.*', 'lang': 'en-us'}])


class KeywordIntentRegistrationTest(unittest.TestCase):
    def check_emitter(self, expected_message_data):
        """Verify that the registration messages matches the expected."""
        for msg_type in self.emitter.get_types():
            self.assertEqual(msg_type, 'register_intent')

        self.assertEqual(
            sorted(self.emitter.get_results(),
                   key=lambda d: sorted(d.items())),
            sorted(expected_message_data, key=lambda d: sorted(d.items())))
        self.emitter.reset()

    def setUp(self):
        self.emitter = MockEmitter()

    def test_register_intent(self):
        intent_service = IntentServiceInterface(self.emitter)
        intent_service.register_adapt_keyword('testA', 'testA', lang='en-US')
        intent_service.register_adapt_keyword('testB', 'testB', lang='en-US')
        self.emitter.reset()

        intent = IntentBuilder("test").require("testA").optionally("testB")
        intent_service.register_adapt_intent("test", intent)
        expected_data = {'at_least_one': [],
                         'name': 'test',
                         'optional': [('testB', 'testB')],
                         'requires': [('testA', 'testA')]}
        self.check_emitter([expected_data])



class UtteranceIntentRegistrationTest(unittest.TestCase):
    def check_emitter(self, expected_message_data):
        """Verify that the registration messages matches the expected."""
        for msg_type in self.emitter.get_types():
            self.assertEqual(msg_type, 'padatious:register_intent')

        self.assertEqual(
            sorted(self.emitter.get_results(),
                   key=lambda d: sorted(d.items())),
            sorted(expected_message_data, key=lambda d: sorted(d.items())))
        self.emitter.reset()

    def setUp(self):
        self.emitter = MockEmitter()

    def test_register_intent(self):
        intent_service = IntentServiceInterface(self.emitter)
        filename = "/tmp/test.intent"
        with open(filename, "w") as f:
            f.write("this is a test\ntest the intent")

        intent_service.register_padatious_intent('test', filename, lang='en-US')
        expected_data = {'file_name': '/tmp/test.intent', 'lang': 'en-US', 'name': 'test'}
        self.check_emitter([expected_data])

