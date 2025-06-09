from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovoscope import End2EndTest


class TestAdaptIntent(TestCase):

    def test_adapt_match(self):
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message(f"{skill_id}.activate",
                        data={},
                        context={"skill_id": skill_id}),
                Message(f"{skill_id}:HelloWorldIntent",
                        data={"utterance": "hello world", "lang": "en-US"},
                        context={"skill_id": skill_id}),
                Message("mycroft.skill.handler.start",
                        data={"name": "HelloWorldSkill.handle_hello_world_intent"},
                        context={"skill_id": skill_id}),
                Message("speak",
                        data={"utterance": "Hello world",
                              "lang": "en-US",
                              "expect_response": False,
                              "meta": {
                                  "dialog": "hello.world",
                                  "data": {},
                                  "skill": skill_id
                              }},
                        context={"skill_id": skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"name": "HelloWorldSkill.handle_hello_world_intent"},
                        context={"skill_id": skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_skill_blacklist(self):
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_skills = [skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        session.blacklisted_intents = [f"{skill_id}:HelloWorldIntent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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

    def test_padatious_match(self):
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            source_message=message,
            expected_messages=[
                message,
                Message(f"{skill_id}.activate",
                        data={},
                        context={"skill_id": skill_id}),
                Message(f"{skill_id}:Greetings.intent",
                        data={"utterance": "good morning", "lang": "en-US"},
                        context={"skill_id": skill_id}),
                Message("mycroft.skill.handler.start",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": skill_id}),
                Message("speak",
                        data={"lang": "en-US",
                              "expect_response": False,
                              "meta": {
                                  "dialog": "hello",
                                  "data": {},
                                  "skill": skill_id
                              }},
                        context={"skill_id": skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"name": "HelloWorldSkill.handle_greetings"},
                        context={"skill_id": skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_skill_blacklist(self):
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin"]
        session.blacklisted_skills = [skill_id]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ["ovos-padatious-pipeline-plugin"]
        session.blacklisted_intents = [f"{skill_id}:Greetings.intent"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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
        skill_id = "ovos-skill-hello-world.openvoiceos"
        session = Session("123")
        session.pipeline = ['ovos-adapt-pipeline-plugin-high']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["good morning"], "lang": "en-US"},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        test = End2EndTest(
            skill_ids=[skill_id],
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
