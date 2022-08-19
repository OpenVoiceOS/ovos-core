import json
import unittest

from ovos_skill_common_query import QuestionsAnswersSkill

from mycroft.skills import FallbackSkill
from ovos_tskill_fakewiki import FakeWikiSkill
from ovos_utils.messagebus import FakeBus, Message


class TestCommonQuery(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            self.bus.emitted_msgs.append(json.loads(msg))

        self.bus.on("message", get_msg)

        self.skill = FakeWikiSkill()
        self.skill._startup(self.bus, "wiki.test")

        self.bus.emitted_msgs = []

        self.cc = QuestionsAnswersSkill()
        self.cc._startup(self.bus, "common_query.test")

    def test_skill_id(self):
        self.assertEqual(self.cc.skill_id, "common_query.test")

        # if running in ovos-core every message will have the skill_id in context
        for msg in self.bus.emitted_msgs:
            self.assertEqual(msg["context"]["skill_id"], "common_query.test")

    def test_intent_register(self):
        # helper .voc files only, no intents
        self.assertTrue(isinstance(self.cc, FallbackSkill))

        adapt_ents = ["common_query_testQuestion"]
        for msg in self.bus.emitted_msgs:
            if msg["type"] == "register_vocab":
                self.assertTrue(msg["data"]["entity_type"] in adapt_ents)

    def test_registered_events(self):
        registered_events = [e[0] for e in self.cc.events]

        # common query event handlers
        common_query = ['question:query.response']
        for event in common_query:
            self.assertTrue(event in registered_events)

        # base skill class events shared with mycroft-core
        default_skill = ["mycroft.skill.enable_intent",
                         "mycroft.skill.disable_intent",
                         "mycroft.skill.set_cross_context",
                         "mycroft.skill.remove_cross_context",
                         "intent.service.skills.deactivated",
                         "intent.service.skills.activated",
                         "mycroft.skills.settings.changed"]
        for event in default_skill:
            self.assertTrue(event in registered_events)

        # base skill class events exclusive to ovos-core
        default_ovos = ["skill.converse.ping",
                        "skill.converse.request",
                        f"{self.cc.skill_id}.activate",
                        f"{self.cc.skill_id}.deactivate"]
        for event in default_ovos:
            self.assertTrue(event in registered_events)

    def test_common_query_events(self):
        self.bus.emitted_msgs = []
        self.cc.handle_question(Message("fallback_cycle_test",
                                        {"utterance": "what is the speed of light"}))

        expected = [
            # thinking animation
            {'type': 'enclosure.mouth.think',
             'data': {},
             'context': {'destination': ['enclosure'],
                         'skill_id': 'common_query.test'}},
            # send query
            {'type': 'question:query',
             'data': {'phrase': 'what is the speed of light'},
             'context': {'skill_id': 'common_query.test'}},
            # skill announces its searching
            {'type': 'question:query.response',
             'data': {'phrase': 'what is the speed of light',
                      'skill_id': 'wiki.test',
                      'searching': True},
             'context': {'skill_id': 'wiki.test'}},
            # skill context set by skill for continuous dialog
            {'type': 'add_context',
             'data': {'context': 'wiki_testFakeWikiKnows',
                      'word': 'what is the speed of light',
                      'origin': ''},
             'context': {'skill_id': 'wiki.test'}},
            # final response
            {'type': 'question:query.response',
             'data': {'phrase': 'what is the speed of light',
                      'skill_id': 'wiki.test',
                      'answer': "answer 1",
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': "answer 1"},
                      'conf': 0.74},
             'context': {'skill_id': 'wiki.test'}},
            # stop thinking animation
            {'type': 'enclosure.mouth.reset',
             'data': {},
             'context': {'destination': ['enclosure'],
                         'skill_id': 'common_query.test'}
             },
            # tell enclosure about active skill (speak method)
            {'type': 'enclosure.active_skill',
             'data': {'skill_id': 'common_query.test'},
             'context': {'destination': ['enclosure'],
                         'skill_id': 'common_query.test'}},
            # execution of speak method
            {'type': 'speak',
             'data': {'utterance': 'answer 1',
                      'expect_response': False,
                      'meta': {'skill': 'common_query.test'},
                      'lang': 'en-us'},
             'context': {'skill_id': 'common_query.test'}},
            # skill callback event
            {'type': 'question:action',
             'data': {'skill_id': 'wiki.test',
                      'phrase': 'what is the speed of light',
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': 'answer 1'}},
             'context': {'skill_id': 'common_query.test'}}
        ]

        for ctr, msg in enumerate(expected):
            m = self.bus.emitted_msgs[ctr]
            self.assertEqual(msg, m)
