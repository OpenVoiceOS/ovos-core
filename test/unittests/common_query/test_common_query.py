import json
import unittest
from unittest.mock import patch

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

    def test_init(self):
        self.assertEqual(self.cc.bus, self.bus)
        self.assertIsInstance(self.cc.skill_id, str)
        self.assertIsInstance(self.cc.active_queries, dict)
        self.assertEqual(self.cc.enclosure.bus, self.bus)
        self.assertEqual(self.cc.enclosure.skill_id, self.cc.skill_id)
        self.assertEqual(len(self.bus.ee.listeners("question:query.response")),
                         1)
        self.assertEqual(len(self.bus.ee.listeners("common_query.question")), 1)

    def test_voc_match(self):
        self.assertTrue(self.cc.voc_match("ocp", "common_play", "en-us", True))
        self.assertTrue(self.cc.voc_match("ocp", "common_play", "en-us", False))
        self.assertFalse(self.cc.voc_match("play music", "common_play", "en-us",
                                           True))
        self.assertTrue(self.cc.voc_match("play music", "common_play", "en-us",
                                          False))

    def test_is_question_like(self):
        lang = "en-us"
        self.assertTrue(self.cc.is_question_like("what is a computer", lang))
        self.assertTrue(self.cc.is_question_like("tell me about computers",
                                                 lang))
        self.assertFalse(self.cc.is_question_like("what computer", lang))
        self.assertFalse(self.cc.is_question_like("play something", lang))
        self.assertFalse(self.cc.is_question_like("play some music", lang))

    def test_match(self):
        # TODO
        pass

    def test_handle_question(self):
        # TODO
        pass

    def test_handle_query_response(self):
        # TODO
        pass

    def test_query_timeout(self):
        # TODO
        pass

    def test_common_query_events(self):
        self.bus.emitted_msgs = []
        self.assertEqual(self.cc.skill_id, "common_query.openvoiceos")

        qq_ctxt = {"source": "audio",
                   "destination": "skills",
                   'skill_id': self.cc.skill_id}
        qq_ans_ctxt = {"source": "skills",
                       "destination": "audio",
                       'skill_id': self.cc.skill_id}
        original_ctxt = dict(qq_ctxt)
        self.bus.emit(Message("common_query.question",
                              {"utterance": "what is the speed of light"},
                              dict(qq_ctxt)))
        self.assertEqual(qq_ctxt, original_ctxt, qq_ctxt)
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
             'context': qq_ctxt},
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
             'context': qq_ctxt},
            # # tell enclosure about active skill (speak method). This is the
            # # skill that provided the response and may follow-up with actions
            # # in a callback method
            # {'type': 'enclosure.active_skill',
            #  'data': {'skill_id': 'wiki.test'},
            #  'context': qq_ctxt},
            # # execution of speak method. This is called from CommonQuery, but
            # # should report the skill which provided the response to match the
            # # enclosure active_skill and any follow-up actions in the callback
            # {'type': 'speak',
            #  'data': {'utterance': 'answer 1',
            #           'expect_response': False,
            #           'meta': {'skill': 'wiki.test'},
            #           'lang': 'en-us'},
            #  'context': skill_ans_ctxt},
            # skill callback event (after response is sent to Audio service)
            # the destination here is `skills` and skill_id context is
            # CommonQuery since this event is not dictated by the selected skill
            {'type': 'question:action',
             'data': {'skill_id': 'wiki.test',
                      'answer': 'answer 1',
                      'conf': 0.74,
                      'handles_speech': True,
                      'phrase': 'what is the speed of light',
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': 'answer 1'}},
             'context': qq_ctxt}
        ]

        for ctr, msg in enumerate(expected):
            m: dict = self.bus.emitted_msgs[ctr]
            if "session" in m.get("context", {}):
                m["context"].pop("session")  # simplify test comparisons
            if "session" in msg.get("context", {}):
                msg["context"].pop("session")  # simplify test comparisons
            self.assertEqual(msg, m, f"idx={ctr}|emitted={m}")

    def test_common_query_events_legacy(self):
        def mock_handle_query(message):
            search_phrase = message.data["phrase"]
            message.context["skill_id"] = self.skill.skill_id
            # First, notify the requestor that we are attempting to handle
            # (this extends a timeout while this skill looks for a match)
            self.bus.emit(message.response({"phrase": search_phrase,
                                            "skill_id": self.skill.skill_id,
                                            "searching": True}))

            result = (None, None, "answer 1",
                      {'query': 'what is the speed of light'})

            if result:
                match = result[0]
                level = result[1]
                answer = result[2]
                callback = result[3] if len(result) > 3 else {}
                confidence = 0.74
                callback["answer"] = answer  # ensure we get it back in CQS_action
                self.bus.emit(message.response({"phrase": search_phrase,
                                                "skill_id": self.skill.skill_id,
                                                "answer": answer,
                                                "handles_speech": False,
                                                "callback_data": callback,
                                                "conf": confidence}))
            else:
                # Signal we are done (can't handle it)
                self.bus.emit(message.response({"phrase": search_phrase,
                                                "skill_id": self.skill.skill_id,
                                                "searching": False}))

        self.bus.remove_all_listeners("question:query")
        self.bus.on("question:query", mock_handle_query)
        self.bus.emitted_msgs = []
        self.assertEqual(self.cc.skill_id, "common_query.openvoiceos")

        qq_ctxt = {"source": "audio",
                   "destination": "skills",
                   'skill_id': self.cc.skill_id}
        qq_ans_ctxt = {"source": "skills",
                       "destination": "audio",
                       'skill_id': self.cc.skill_id}
        original_ctxt = dict(qq_ctxt)
        self.bus.emit(Message("common_query.question",
                              {"utterance": "what is the speed of light"},
                              dict(qq_ctxt)))
        self.assertEqual(qq_ctxt, original_ctxt, qq_ctxt)
        skill_ctxt = {"source": "audio", "destination": "skills",
                      'skill_id': 'wiki.test'}
        skill_ans_ctxt = {"source": "skills", "destination": "audio",
                          'skill_id': 'wiki.test'}

        expected = [
            # original query
            {'context': qq_ctxt,
             'data': {'utterance': 'what is the speed of light'},
             'type': 'common_query.question'},
            # thinking animation
            {'type': 'enclosure.mouth.think',
             'data': {},
             'context': qq_ctxt},
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
            # final response
            {'type': 'question:query.response',
             'data': {'phrase': 'what is the speed of light',
                      'skill_id': 'wiki.test',
                      'answer': "answer 1",
                      'handles_speech': False,
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': "answer 1"},
                      'conf': 0.74},
             'context': skill_ctxt},
            # stop thinking animation
            {'type': 'enclosure.mouth.reset',
             'data': {},
             'context': qq_ctxt},
            # tell enclosure about active skill (speak method). This is the
            # skill that provided the response and may follow-up with actions
            # in a callback method
            {'type': 'enclosure.active_skill',
             'data': {'skill_id': 'wiki.test'},
             'context': qq_ctxt},
            # execution of speak method. This is called from CommonQuery, but
            # should report the skill which provided the response to match the
            # enclosure active_skill and any follow-up actions in the callback
            {'type': 'speak',
             'data': {'utterance': 'answer 1',
                      'expect_response': False,
                      'meta': {'skill': 'wiki.test'},
                      'lang': 'en-us'},
             'context': skill_ans_ctxt},
            # skill callback event (after response is sent to Audio service)
            # the destination here is `skills` and skill_id context is
            # CommonQuery since this event is not dictated by the selected skill
            {'type': 'question:action',
             'data': {'skill_id': 'wiki.test',
                      'answer': 'answer 1',
                      'conf': 0.74,
                      'handles_speech': False,
                      'phrase': 'what is the speed of light',
                      'callback_data': {'query': 'what is the speed of light',
                                        'answer': 'answer 1'}},
             'context': qq_ctxt}
        ]

        for ctr, msg in enumerate(expected):
            m: dict = self.bus.emitted_msgs[ctr]
            if "session" in m.get("context", {}):
                m["context"].pop("session")  # simplify test comparisons
            if "session" in msg.get("context", {}):
                msg["context"].pop("session")  # simplify test comparisons
            self.assertEqual(msg, m, f"idx={ctr}|emitted={m}")
