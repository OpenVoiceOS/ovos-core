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

        qq_ctxt = {"source": "audio", "destination": "skills", 'skill_id': self.cc.skill_id}
        qq_ans_ctxt = {"source": "skills", "destination": "audio", 'skill_id': self.cc.skill_id}
        self.bus.emit(Message("common_query.question",
                              {"utterance": "what is the speed of light"},
                              qq_ctxt))

        skill_ctxt = {"source": "audio", "destination": "skills", 'skill_id': 'wiki.test'}
        skill_ans_ctxt = {"source": "skills", "destination": "audio", 'skill_id': 'wiki.test'}

        expected = [
            # original query
            {'context': qq_ctxt,
             'data': {'utterance': 'what is the speed of light'},
             'type': 'common_query.question'},
            # thinking animation
            {'type': 'enclosure.mouth.think',
             'data': {},
             'context': {'destination': "skills", 'source': 'audio',
                         'skill_id': self.cc.skill_id}},
            # send query
            {'type': 'question:query',
             'data': {'phrase': 'what is the speed of light'},
             'context': qq_ans_ctxt},
            # skill announces its searching
            {'type': 'question:query.response',
             'data': {'phrase': 'what is the speed of light',
                      'skill_id': 'wiki.test',
                      'searching': True},
             'context': skill_ctxt},
            # skill context set by skill for continuous dialog
            {'type': 'add_context',
             'data': {'context': 'wiki_testFakeWikiKnows',
                      'word': 'what is the speed of light',
                      'origin': ''},
             'context': skill_ans_ctxt},
            # final response
            {'type': 'question:query.response',
             'data': {'phrase': 'what is the speed of light',
                      'skill_id': 'wiki.test',
                      'answer': "answer 1",
                      'handles_speech': True,
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': "answer 1"},
                      'conf': 0.74},
             'context': skill_ctxt},
            # stop thinking animation
            {'type': 'enclosure.mouth.reset',
             'data': {},
             'context': {'destination': "audio", 'source': 'skills',
                         'skill_id': "wiki.test"}
             },
            # skill callback event
            {'type': 'question:action',
             'data': {'skill_id': 'wiki.test',
                      'phrase': 'what is the speed of light',
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': 'answer 1'}},
             'context': skill_ans_ctxt},
            # tell enclosure about active skill (speak method)
            {'type': 'enclosure.active_skill',
             'data': {'skill_id': 'wiki.test'},
             'context': {'destination': "audio", 'source': 'skills',
                         'skill_id': 'wiki.test'}},
            # execution of speak method
            {'type': 'speak',
             'data': {'utterance': 'answer 1',
                      'expect_response': False,
                      'meta': {'skill': 'wiki.test'},
                      'lang': 'en-us'},
             'context': skill_ans_ctxt},
        ]

        for ctr, msg in enumerate(expected):
            m = self.bus.emitted_msgs[ctr]
            self.assertEqual(msg, m)
