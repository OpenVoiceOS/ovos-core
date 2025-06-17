import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestStopNoSkills(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.minicroft = get_minicroft([])  # reuse for speed, but beware if skills keeping internal state        # to make tests easier to grok
        self.ignore_messages = ["speak",
                                "ovos.common_play.stop.response",
                                "common_query.openvoiceos.stop.response",
                                "persona.openvoiceos.stop.response"
                                ]

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_exact(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            # keep_original_src=["stop.openvoiceos.activate"], # TODO
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

                Message("stop:global", {}),  # global stop, no active skill
                Message("mycroft.stop", {}),

                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute()

    def test_not_exact_high(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["could you stop that"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )

        test.execute()

    def test_not_exact_med(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-medium']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["could you stop that"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            ignore_messages=self.ignore_messages,
            # keep_original_src=["stop.openvoiceos.activate"], # TODO
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

                Message("stop:global", {}),  # global stop, no active skill
                Message("mycroft.stop", {}),

                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute()


class TestCountSkills(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])  # reuse for speed, but beware if skills keeping internal state
        # to make tests easier to grok
        self.ignore_messages = ["speak",
                                "ovos.common_play.stop.response",
                                "common_query.openvoiceos.stop.response",
                                "persona.openvoiceos.stop.response"
                                ]

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_count(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-high', "ovos-padatious-pipeline-plugin-high"]

        message = Message("recognizer_loop:utterance",
                          {"utterances": ["count to 3"], "lang": session.lang},
                          {"session": session.serialize()})

        # first count to 10 to validate skill is working
        activate_skill = [
            message,
            Message(f"{self.skill_id}.activate", {}),  # skill is activated
            Message(f"{self.skill_id}:count_to_N.intent", {}),  # intent triggers

            Message("mycroft.skill.handler.start", {
                "name": "CountSkill.handle_how_are_you_intent"
            }),
            # here would be N speak messages, but we ignore them in this test
            Message("mycroft.skill.handler.complete", {
                "name": "CountSkill.handle_how_are_you_intent"
            }),

            Message("ovos.utterance.handled", {})
        ]
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            # keep_original_src=[f"{self.skill_id}.activate"], # TODO
            expected_messages=activate_skill
        )
        test.execute()

    def test_count_infinity_active(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-high',
                            "ovos-padatious-pipeline-plugin-high"]

        def make_it_count():
            nonlocal session
            message = Message("recognizer_loop:utterance",
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})
            session.activate_skill(self.skill_id)  # ensure in active skill list
            self.minicroft.bus.emit(message)

        # count to infinity, the skill will keep running in the background
        create_daemon(make_it_count)

        time.sleep(2)

        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        stop_skill_active = [
            message,
            Message(f"{self.skill_id}.stop.ping",
                    {"skill_id":self.skill_id}),
            Message("skill.stop.pong",
                    {"skill_id": self.skill_id, "can_handle": True},
                    {"skill_id": self.skill_id}),

            Message("stop.openvoiceos.activate",
                    context={"skill_id": "stop.openvoiceos"}),
            Message("stop:skill",
                    context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop",
                    context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop.response",
                    {"skill_id": self.skill_id, "result": True},
                    {"skill_id": self.skill_id}),

            # async stop pipeline callback emits these messages
            # but we cant guarantee where in the test they will be emitted

            # if skill is in middle of get_response
            #Message("mycroft.skills.abort_question",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # if skill is in active_list
            #Message("ovos.skills.converse.force_timeout",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # if skill is executing TTS
            #Message("mycroft.audio.speech.stop",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # the intent running in the daemon thread exits cleanly
            Message("mycroft.skill.handler.complete",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id}),
            Message("ovos.utterance.handled",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id})
        ]
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=[],
            flip_points=["recognizer_loop:utterance"],
            # messages in 'keep_original_src' would not be sent to hivemind clients
            # i.e. they are directed towards ovos-core
            keep_original_src=[f"{self.skill_id}.stop.ping",
                               f"{self.skill_id}.stop",
                               "mycroft.skills.abort_question",
                               "ovos.skills.converse.force_timeout",
                               # "stop.openvoiceos.activate" # TODO
                               ],
            async_messages=[
                "ovos.skills.converse.force_timeout"
            ], # order that it wil be received unknown
            ignore_messages=self.ignore_messages,
            source_message=message,
            expected_messages=stop_skill_active
        )
        test.execute()

    def test_count_infinity_global(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-stop-pipeline-plugin-high',
                            "ovos-padatious-pipeline-plugin-high"]

        def make_it_count():
            message = Message("recognizer_loop:utterance",
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize()})
            self.minicroft.bus.emit(message)

        # count to infinity, the skill will keep running in the background
        create_daemon(make_it_count)

        time.sleep(3)

        # NOTE: skill not in active skill list for this Session, global stop will match instead
        # this doesnt typically happen at runtime, but possible since clients send whatever Session they want
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})
        stop_skill_from_global = [
            message,
            Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

            Message("stop:global", {}),  # global stop, no active skill
            Message("mycroft.stop", {}),

            Message(f"{self.skill_id}.stop.response",
                    {"skill_id": self.skill_id, "result": True}),
            Message("ovos.utterance.handled", {})
        ]
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            expected_messages=stop_skill_from_global,
            #keep_original_src=["stop.openvoiceos.activate"],  # TODO
        )
        test.execute()

    def test_count_infinity_stop_low(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-padatious-pipeline-plugin-high",
                            'ovos-stop-pipeline-plugin-low']

        def make_it_count():
            nonlocal session
            message = Message("recognizer_loop:utterance",
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})
            session.activate_skill(self.skill_id)  # ensure in active skill list
            self.minicroft.bus.emit(message)

        # count to infinity, the skill will keep running in the background
        create_daemon(make_it_count)

        time.sleep(2)

        message = Message("recognizer_loop:utterance",
                          {"utterances": ["full stop"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        stop_skill_active = [
            message,
            Message(f"{self.skill_id}.stop.ping",
                    {"skill_id":self.skill_id}),
            Message("skill.stop.pong",
                    {"skill_id": self.skill_id, "can_handle": True},
                    {"skill_id": self.skill_id}),

            Message("stop.openvoiceos.activate",
                    context={"skill_id": "stop.openvoiceos"}),
            Message("stop:skill",
                    context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop",
                    context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop.response",
                    {"skill_id": self.skill_id, "result": True},
                    {"skill_id": self.skill_id}),

            # async stop pipeline callback emits these messages
            # but we cant guarantee where in the test they will be emitted

            # if skill is in middle of get_response
            #Message("mycroft.skills.abort_question",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # if skill is in active_list
            #Message("ovos.skills.converse.force_timeout",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # if skill is executing TTS
            #Message("mycroft.audio.speech.stop",
            #        {"skill_id": self.skill_id},
            #        {"skill_id": self.skill_id}),

            # the intent running in the daemon thread exits cleanly
            Message("mycroft.skill.handler.complete",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id}),
            Message("ovos.utterance.handled",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id})
        ]
        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=[],
            flip_points=["recognizer_loop:utterance"],
            # messages in 'keep_original_src' would not be sent to hivemind clients
            # i.e. they are directed towards ovos-core
            keep_original_src=[f"{self.skill_id}.stop.ping",
                               f"{self.skill_id}.stop",
                               "mycroft.skills.abort_question",
                               # "stop.openvoiceos.activate", # TODO
                               "ovos.skills.converse.force_timeout"],
            ignore_messages=self.ignore_messages,
            async_messages=[
                "ovos.skills.converse.force_timeout"
            ], # order that it wil be received unknown
            source_message=message,
            expected_messages=stop_skill_active
        )
        test.execute()
