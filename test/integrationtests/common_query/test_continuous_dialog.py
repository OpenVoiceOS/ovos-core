import json
import unittest

from ovos_tskill_fakewiki import FakeWikiSkill
from ovos_utils.messagebus import FakeBus, Message


class TestDialog(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            m = json.loads(msg)
            if "session" in m.get("context", {}):
                m["context"].pop("session")  # simplify tests
            self.bus.emitted_msgs.append(m)

        self.bus.on("message", get_msg)

        self.skill = FakeWikiSkill()
        self.skill._startup(self.bus, "wiki.test")

        self.skill.has_context = False

        def set_context(message):
            self.skill.has_context = True

        def unset_context(message):
            self.skill.has_context = False

        self.bus.on('add_context', set_context)
        self.bus.on('remove_context', unset_context)

    def test_continuous_dialog(self):
        self.bus.emitted_msgs = []

        # "ask the wiki X"
        self.assertFalse(self.skill.has_context)
        self.skill.handle_search(Message("search_fakewiki.intent",
                                         {"query": "what is the speed of light"}))

        self.assertEqual(self.bus.emitted_msgs[0],
                         {'context': {'skill_id': 'wiki.test'},
                          'data': {'context': 'wiki_testFakeWikiKnows',
                                   'origin': '',
                                   'word': 'what is the speed of light'},
                          'type': 'add_context'})
        self.assertEqual(self.bus.emitted_msgs[-1],
                         {'context': {'skill_id': 'wiki.test'},
                          'data': {'expect_response': False,
                                   'lang': 'en-us',
                                   'meta': {'skill': 'wiki.test'},
                                   'utterance': 'answer 1'},
                          'type': 'speak'})

        # "tell me more"
        self.assertTrue(self.skill.has_context)
        self.skill.handle_tell_more(Message("FakeWikiMore"))

        self.assertEqual(self.bus.emitted_msgs[-1],
                         {'context': {'skill_id': 'wiki.test'},
                          'data': {'expect_response': False,
                                   'lang': 'en-us',
                                   'meta': {'skill': 'wiki.test'},
                                   'utterance': 'answer 2'},
                          'type': 'speak'})
        self.assertTrue(self.skill.has_context)

        # "tell me more" - no more data dialog
        self.skill.handle_tell_more(Message("FakeWikiMore"))

        self.assertEqual(self.bus.emitted_msgs[-2]["type"], "speak")
        self.assertEqual(self.bus.emitted_msgs[-2]["data"]["meta"],
                         {'skill': 'wiki.test'})

        # removal of context to disable "tell me more"
        self.assertEqual(self.bus.emitted_msgs[-1],
                         {'context': {'skill_id': 'wiki.test'},
                          'data': {'context': 'wiki_testFakeWikiKnows'},
                          'type': 'remove_context'})
        self.assertFalse(self.skill.has_context)
