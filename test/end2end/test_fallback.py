from unittest import TestCase
from copy import deepcopy
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestFallback(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-fallback-unknown.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_fallback_match(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-fallback-pipeline-plugin-low']
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        final_session = deepcopy(session)
        # final_session.active_skills = [(self.skill_id, 0.0)] # TODO - failing


        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            final_session=final_session,
            keep_original_src=[
                "ovos.skills.fallback.ping",
                # "ovos.skills.fallback.pong", # TODO
            ],
            activation_points=[f"ovos.skills.fallback.{self.skill_id}.request"],
            source_message=message,
            expected_messages=[
                message,
                Message("ovos.skills.fallback.ping",
                        {"utterances": ["hello world"], "lang": session.lang, "range": [90, 101]}),
                Message("ovos.skills.fallback.pong", {"skill_id": self.skill_id, "can_handle": True}),
                Message(f"ovos.skills.fallback.{self.skill_id}.request",
                        {"utterances": ["hello world"], "lang": session.lang, "range": [90, 101], "skill_id": self.skill_id}),
                Message(f"ovos.skills.fallback.{self.skill_id}.start", {}),
                Message("speak",
                        data={"lang": session.lang,
                              "expect_response": False,
                              "meta": {
                                  "dialog": "unknown",
                                  "data": {},
                                  "skill": self.skill_id
                              }},
                        context={"skill_id": self.skill_id}),
                Message(f"ovos.skills.fallback.{self.skill_id}.response",
                        data={"fallback_handler":"UnknownSkill.handle_fallback"},
                        context={"skill_id": self.skill_id}),

                Message("ovos.utterance.handled", {})
            ]
        )

        test.execute(timeout=10)
