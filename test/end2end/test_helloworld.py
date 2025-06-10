from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft


class TestAdaptIntent(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_adapt_match(self):
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}:HelloWorldIntent",
                        data={"utterance": "hello world", "lang": "en-US"},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.start",
                        data={"name": "HelloWorldSkill.handle_hello_world_intent"},
                        context={"skill_id": self.skill_id}),
                Message("speak",
                        data={"utterance": "Hello world",
                              "lang": "en-US",
                              "expect_response": False,
                              "meta": {
                                  "dialog": "hello.world",
                                  "data": {},
                                  "skill": self.skill_id
                              }},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"name": "HelloWorldSkill.handle_hello_world_intent"},
                        context={"skill_id": self.skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_skill_blacklist(self):
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)

    def test_intent_blacklist(self):
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_intents = [f"{self.skill_id}:HelloWorldIntent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)

    def test_padatious_no_match(self):
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)


class TestPadatiousIntent(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_padatious_match(self):
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}:Greetings.intent",
                        data={"utterance": "good morning", "lang": "en-US"},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.start",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": self.skill_id}),
                Message("speak",
                        data={"lang": "en-US",
                              "expect_response": False,
                              "meta": {
                                  "dialog": "hello",
                                  "data": {},
                                  "skill": self.skill_id
                              }},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": self.skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_skill_blacklist(self):
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)

    def test_intent_blacklist(self):
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        session.blacklisted_intents = [f"{self.skill_id}:Greetings.intent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)

    def test_adapt_no_match(self):
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)


class TestModel2VecIntent(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_m2v_match(self):
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}:Greetings.intent",
                        data={"utterance": "good morning", "lang": "en-US"},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.start",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": self.skill_id}),
                Message("speak",
                        data={"lang": "en-US",
                              "expect_response": False,
                              "meta": {
                                  "dialog": "hello",
                                  "data": {},
                                  "skill": self.skill_id
                              }},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": self.skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_skill_blacklist(self):
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)

    def test_intent_blacklist(self):
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        session.blacklisted_intents = [f"{self.skill_id}:Greetings.intent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)
