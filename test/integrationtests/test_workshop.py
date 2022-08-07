import json
import unittest
from os.path import dirname
from time import sleep
from ovos_workshop.skills import OVOSSkill, MycroftSkill
from mycroft.skills.skill_loader import SkillLoader
from ovos_utils.messagebus import FakeBus, Message

# tests taken from ovos_workshop


class TestSkill(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            msg = json.loads(msg)
            self.bus.emitted_msgs.append(msg)

        self.bus.on("message", get_msg)

        self.skill = SkillLoader(self.bus, f"{dirname(__file__)}/ovos_tskill_abort")
        self.skill.skill_id = "abort.test"
        self.bus.emitted_msgs = []

        self.skill.load()

    def test_skill_id(self):
        self.assertTrue(isinstance(self.skill.instance, OVOSSkill))
        self.assertTrue(isinstance(self.skill.instance, MycroftSkill))

        self.assertEqual(self.skill.skill_id, "abort.test")
        # if running in ovos-core every message will have the skill_id in context
        for msg in self.bus.emitted_msgs:
            if msg["type"] == 'mycroft.skills.loaded': # emitted by SkillLoader, not by skill
                continue
            self.assertEqual(msg["context"]["skill_id"], "abort.test")

    def test_intent_register(self):
        padatious_intents = ["abort.test:test.intent",
                             "abort.test:test2.intent",
                             "abort.test:test3.intent"]
        for msg in self.bus.emitted_msgs:
            if msg["type"] == "padatious:register_intent":
                self.assertTrue(msg["data"]["name"] in padatious_intents)

    def test_registered_events(self):
        registered_events = [e[0] for e in self.skill.instance.events]

        # intent events
        intent_triggers = [f"{self.skill.skill_id}:test.intent",
                           f"{self.skill.skill_id}:test2.intent",
                           f"{self.skill.skill_id}:test3.intent"
                           ]
        for event in intent_triggers:
            self.assertTrue(event in registered_events)

        # base skill class events shared with mycroft-core
        default_skill = ["mycroft.skill.enable_intent",
                         "mycroft.skill.disable_intent",
                         "mycroft.skill.set_cross_context",
                         "mycroft.skill.remove_cross_context",
                         "mycroft.skills.settings.changed"]
        for event in default_skill:
            self.assertTrue(event in registered_events)

        # base skill class events exclusive to ovos-core
        default_ovos = ["skill.converse.ping",
                        "skill.converse.request",
                        "intent.service.skills.activated",
                        "intent.service.skills.deactivated",
                        f"{self.skill.skill_id}.activate",
                        f"{self.skill.skill_id}.deactivate"]
        for event in default_ovos:
            self.assertTrue(event in registered_events)

    def tearDown(self) -> None:
        self.skill.unload()


class TestKillableIntents(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            m = json.loads(msg)
            m.pop("context")
            self.bus.emitted_msgs.append(m)

        self.bus.on("message", get_msg)

        self.skill = SkillLoader(self.bus, f"{dirname(__file__)}/ovos_tskill_abort")
        self.skill.skill_id = "abort.test"
        self.skill.load()

    def test_skills_abort_event(self):
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.assertTrue(self.skill.instance.my_special_var == "default")
        self.bus.emit(Message(f"{self.skill.skill_id}:test.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_abort_intent'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'still here', 'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}
        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.instance.my_special_var == "changed")

        # check that intent reacts to mycroft.skills.abort_execution
        # eg, gui can emit this event if some option was selected
        # on screen to abort the current voice interaction
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"mycroft.skills.abort_execution"))
        sleep(2)

        # check that stop method was called
        self.assertTrue(self.skill.instance.stop_called)

        # check that TTS stop message was emmited
        tts_stop = {'type': 'mycroft.audio.speech.stop', 'data': {}}
        self.assertIn(tts_stop, self.bus.emitted_msgs)

        # check that cleanup callback was called
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'I am dead', 'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.instance.my_special_var == "default")

        # check that we are not getting speak messages anymore
        self.bus.emitted_msgs = []
        sleep(2)
        self.assertTrue(self.bus.emitted_msgs == [])

    def test_skill_stop(self):
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.assertTrue(self.skill.instance.my_special_var == "default")
        self.bus.emit(Message(f"{self.skill.skill_id}:test.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_abort_intent'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'still here', 'expect_response': False,
                              'meta': {'skill': 'abort.test'}, 'lang': 'en-us'}}
        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.instance.my_special_var == "changed")

        # check that intent reacts to skill specific stop message
        # this is also emitted on mycroft.stop if using OvosSkill class
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"{self.skill.skill_id}.stop"))
        sleep(2)

        # check that stop method was called
        self.assertTrue(self.skill.instance.stop_called)

        # check that TTS stop message was emmited
        tts_stop = {'type': 'mycroft.audio.speech.stop', 'data': {}}
        self.assertIn(tts_stop, self.bus.emitted_msgs)

        # check that cleanup callback was called
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'I am dead', 'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}

        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.instance.my_special_var == "default")

        # check that we are not getting speak messages anymore
        self.bus.emitted_msgs = []
        sleep(2)
        self.assertTrue(self.bus.emitted_msgs == [])

    def test_get_response(self):
        """ send "mycroft.skills.abort_question" and
        confirm only get_response is aborted, speech after is still spoken"""
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.bus.emit(Message(f"{self.skill.skill_id}:test2.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_get_response_intent'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'this is a question',
                              'expect_response': True,
                              'meta': {'dialog': 'question', 'data': {}, 'skill': 'abort.test'},
                              'lang': 'en-us'}}
        activate_msg = {'type': 'intent.service.skills.activate', 'data': {'skill_id': 'abort.test'}}

        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertIn(activate_msg, self.bus.emitted_msgs)

        # check that get_response loop is aborted
        # but intent continues executing
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"mycroft.skills.abort_question"))
        sleep(1)

        # check that stop method was NOT called
        self.assertFalse(self.skill.instance.stop_called)

        # check that speak message after get_response loop was spoken
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'question aborted',
                              'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}
        self.assertIn(speak_msg, self.bus.emitted_msgs)

    def test_developer_stop_msg(self):
        """ send "my.own.abort.msg" and confirm intent3 is aborted
        send "mycroft.skills.abort_execution" and confirm intent3 ignores it"""
        self.bus.emitted_msgs = []
        # skill will enter a infinite loop unless aborted
        self.bus.emit(Message(f"{self.skill.skill_id}:test3.intent"))
        sleep(2)
        # check that intent triggered
        start_msg = {'type': 'mycroft.skill.handler.start',
                     'data': {'name': 'KillableSkill.handle_test_msg_intent'}}
        speak_msg = {'type': 'speak',
                     'data': {'utterance': "you can't abort me",
                              'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}
        self.assertIn(start_msg, self.bus.emitted_msgs)
        self.assertIn(speak_msg, self.bus.emitted_msgs)

        # check that intent does NOT react to mycroft.skills.abort_execution
        # developer requested a dedicated abort message
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"mycroft.skills.abort_execution"))
        sleep(1)

        # check that stop method was NOT called
        self.assertFalse(self.skill.instance.stop_called)

        # check that intent reacts to my.own.abort.msg
        self.bus.emitted_msgs = []
        self.bus.emit(Message(f"my.own.abort.msg"))
        sleep(2)

        # check that stop method was called
        self.assertTrue(self.skill.instance.stop_called)

        # check that TTS stop message was emmited
        tts_stop = {'type': 'mycroft.audio.speech.stop', 'data': {}}
        self.assertIn(tts_stop, self.bus.emitted_msgs)

        # check that cleanup callback was called
        speak_msg = {'type': 'speak',
                     'data': {'utterance': 'I am dead', 'expect_response': False,
                              'meta': {'skill': 'abort.test'},
                              'lang': 'en-us'}}
        self.assertIn(speak_msg, self.bus.emitted_msgs)
        self.assertTrue(self.skill.instance.my_special_var == "default")

        # check that we are not getting speak messages anymore
        self.bus.emitted_msgs = []
        sleep(2)
        self.assertTrue(self.bus.emitted_msgs == [])
