from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovoscope import End2EndTest, get_minicroft


class TestAdaptIntent(TestCase):

    def setUp(self):
        """
        Initializes the test environment before each test.
        
        Sets the logging level to DEBUG, assigns the skill ID for the "hello world" skill, and creates a Minicroft instance with the skill loaded for use in tests.
        """
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        """
        Stops the minicroft instance if running and resets the logging level to CRITICAL after each test.
        """
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_adapt_match(self):
        """
        Tests that the Adapt pipeline correctly recognizes and handles the "hello world" utterance.
        
        Simulates an end-to-end interaction using the Adapt intent parsing pipeline, verifying that the expected sequence of messages is produced for a successful intent match and skill response.
        """
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that a blacklisted skill does not handle an utterance in the Adapt pipeline.
        
        Verifies that when the skill is blacklisted in the session, the utterance results in an error sound, intent failure, and handled confirmation, without activating the skill.
        """
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that blacklisting a specific intent prevents it from being triggered.
        
        Creates a session using the Adapt pipeline with the `HelloWorldIntent` blacklisted. Sends a "hello world" utterance and verifies that the system responds with an error sound, intent failure, and utterance handled messages, confirming the intent is blocked.
        """
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_intents = [f"{self.skill_id}:HelloWorldIntent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that the Padatious pipeline does not match the "hello world" utterance.
        
        Verifies that when using the Padatious pipeline with an utterance that has no matching intent, the system emits an error sound, a complete intent failure message, and marks the utterance as handled.
        """
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Initializes the test environment before each test.
        
        Sets the logging level to DEBUG, assigns the skill ID for the hello world skill, and creates a minicroft instance with the skill loaded.
        """
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        """
        Stops the minicroft instance if running and resets the logging level to CRITICAL after each test.
        """
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_padatious_match(self):
        """
        Tests that the Padatious pipeline correctly matches the "good morning" utterance and triggers the expected skill activation, intent recognition, handler execution, and response messages.
        """
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that a blacklisted skill does not handle an utterance in the Padatious pipeline.
        
        Verifies that when the skill is blacklisted in the session, the utterance results in an error sound, intent failure, and utterance handled messages, confirming the skill is blocked from activation.
        """
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that blacklisting a specific intent prevents it from being recognized and handled.
        
        Simulates an utterance that would normally match the blacklisted intent using the Padatious pipeline. Verifies that the system responds with an error sound, completes intent failure, and marks the utterance as handled without activating the skill.
        """
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        session.blacklisted_intents = [f"{self.skill_id}:Greetings.intent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that the Adapt pipeline does not match an unrelated utterance and triggers intent failure.
        
        Sends a "good morning" utterance using the Adapt pipeline and verifies that the system responds with an error sound, a complete intent failure message, and an utterance handled message, indicating no skill or intent was matched.
        """
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Initializes the test environment before each test.
        
        Sets the logging level to DEBUG, assigns the skill ID for the hello world skill, and creates a minicroft instance with the skill loaded.
        """
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        """
        Stops the minicroft instance if running and resets the logging level to CRITICAL after each test.
        """
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_m2v_match(self):
        """
        Tests that the Model2Vec pipeline correctly matches the "good morning" utterance to the Greetings intent and triggers the expected sequence of skill activation, intent handling, and response messages.
        """
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that a blacklisted skill does not handle an utterance in the Model2Vec pipeline.
        
        Verifies that when the skill is blacklisted in the session, the utterance results in an error sound, intent failure, and utterance handled messages, confirming the skill is blocked from activation.
        """
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        session.blacklisted_skills = [self.skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
        """
        Tests that blacklisting a specific intent prevents it from being recognized and handled.
        
        Sends a "good morning" utterance using the Model2Vec pipeline with the `Greetings.intent` blacklisted. Verifies that the system responds with an error sound, completes intent failure, and marks the utterance as handled without activating the skill.
        """
        session = Session("123")
        session.pipeline = ["ovos-m2v-pipeline-high"]
        session.blacklisted_intents = [f"{self.skill_id}:Greetings.intent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)
