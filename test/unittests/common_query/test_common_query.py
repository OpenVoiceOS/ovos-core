import json
import unittest

from mycroft.skills.intent_services.commonqa_service import CommonQAService
from ovos_tskill_fakewiki import FakeWikiSkill
from ovos_utils.messagebus import FakeBus, Message


class TestCommonQuery(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            self.bus.emitted_msgs.append(json.loads(msg))

        self.skill = FakeWikiSkill()
        self.skill._startup(self.bus, "wiki.test")

        self.cc = CommonQAService(self.bus)

        self.bus.on("message", get_msg)

    def test_common_query_events(self):
        self.bus.emitted_msgs = []
        self.assertEqual(self.cc.skill_id, "common_query.openvoiceos")

        self.bus.emit(Message("common_query.question",
                              {"utterance": "what is the speed of light"}))

        expected = [
            # original query
            {'context': {},
             'data': {'utterance': 'what is the speed of light'},
             'type': 'common_query.question'},
            # thinking animation
            {'type': 'enclosure.mouth.think',
             'data': {},
             'context': {'destination': ['enclosure'],
                         'skill_id': self.cc.skill_id}},
            # send query
            {'type': 'question:query',
             'data': {'phrase': 'what is the speed of light'},
             'context': {'skill_id': self.cc.skill_id}},
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
                         'skill_id': self.cc.skill_id}
             },
            # tell enclosure about active skill (speak method)
            {'type': 'enclosure.active_skill',
             'data': {'skill_id': self.cc.skill_id},
             'context': {'destination': ['enclosure'],
                         'skill_id': self.cc.skill_id}},
            # execution of speak method
            {'type': 'speak',
             'data': {'utterance': 'answer 1',
                      'expect_response': False,
                      'meta': {'skill': self.cc.skill_id},
                      'lang': 'en-us'},
             'context': {'skill_id': self.cc.skill_id}},
            # skill callback event
            {'type': 'question:action',
             'data': {'skill_id': 'wiki.test',
                      'phrase': 'what is the speed of light',
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': 'answer 1'}},
             'context': {'skill_id': self.cc.skill_id}}
        ]

        for ctr, msg in enumerate(expected):
            m = self.bus.emitted_msgs[ctr]
            self.assertEqual(msg, m)
