# Copyright 2026 OpenVoiceOS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""OVOS-SESSION-1 3.2.1 / 3.2.7 - the match language is not a session preference.

``session.lang`` is the participant's standing input-side preference. It is
"stable across the session, not derived from any one utterance"
(OVOS-SESSION-1 3.2.1), and intake resolution "MUST NOT mutate" the language
signals it reads (3.2.7).

Under ``multilingual_matching`` the orchestrator calls a pipeline plugin once
per candidate language, so a match can land in a member of
``secondary_langs``. The match language belongs on the dispatch payload
(``data.lang``, 3.2.8) and on the 9.2 notification. It does not belong in the
default-session store: OVOS-SESSION-2 5.1 enumerates the two writes that apply
on top of a committed match snapshot - the PIPELINE-1 7.1 ``active_handlers``
push and the CONTEXT-1 5.3 ``intent_context`` merge - and ``lang`` is not one
of them.
"""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.service import IntentService

MATCHED = SpecMessage.INTENT_MATCHED.value


class TestDispatchDoesNotWriteMatchLangToStore(unittest.TestCase):
    """A nl-NL default session that matches in en-US stays nl-NL."""

    def setUp(self):
        SessionManager.default_session = Session("default")
        SessionManager.default_session.lang = "nl-NL"
        SessionManager.default_session.secondary_langs = ["en-US"]
        SessionManager.sessions = {"default": SessionManager.default_session}

        self.bus = FakeBus()
        svc = IntentService.__new__(IntentService)
        svc.bus = self.bus
        svc.config = {"multilingual_matching": True}
        svc.pipeline_plugins = {}
        svc._deactivations = defaultdict(list)
        ut = MagicMock(); ut.transform.side_effect = lambda u, c: (u, c)
        svc.utterance_plugins = ut
        mt = MagicMock(); mt.transform.side_effect = lambda c: c
        svc.metadata_plugins = mt
        it = MagicMock(); it.transform.side_effect = lambda i: i
        svc.intent_plugins = it
        svc.status = MagicMock()
        svc.intent_manifest = MagicMock()
        svc.intent_manifest.get_context_requirements.return_value = ([], [])
        svc.intent_dispatcher = IntentDispatcher(
            self.bus, timeout=0, on_terminal=svc._emit_utterance_handled)
        self.svc = svc

        self.dispatched = []
        self.bus.on("test.skill:do", self.dispatched.append)
        self.matched = []
        self.bus.on(MATCHED, self.matched.append)

    def tearDown(self):
        self.svc.intent_dispatcher.shutdown()
        SessionManager.default_session = Session("default")
        SessionManager.sessions = {"default": SessionManager.default_session}

    def _dispatch_in_en(self):
        """Dispatch a default-session utterance whose match landed in en-US."""
        match = IntentHandlerMatch(match_type="test.skill:do",
                                   match_data={}, skill_id="test.skill",
                                   utterance="turn on the light")
        msg = Message(SpecMessage.UTTERANCE,
                      {"utterances": ["turn on the light"]},
                      {"session": SessionManager.default_session.serialize()})
        self.svc._dispatch_match(match, msg, "en-US", pipeline_id="p1")

    def test_store_keeps_the_preference(self):
        # SESSION-1 3.2.1: `lang` is stable across the session and is not
        # derived from any one utterance; SESSION-1 3.2.7: resolution reads
        # the signals and MUST NOT mutate them.
        self._dispatch_in_en()
        self.assertEqual(SessionManager.default_session.lang, "nl-NL")

    def test_secondary_langs_still_excludes_the_preference(self):
        # SESSION-1 3.2.2: `secondary_langs` MUST NOT contain `lang`. Writing
        # the match language onto `lang` breaks that invariant too, because
        # en-US is already in the pool.
        self._dispatch_in_en()
        self.assertNotIn(SessionManager.default_session.lang,
                         SessionManager.default_session.secondary_langs)

    def test_dispatch_payload_carries_the_match_lang(self):
        # SESSION-1 3.2.8 / PIPELINE-1 9.1: the match language reaches the
        # handler on `data.lang`, which is where a consumer reads it.
        self._dispatch_in_en()
        self.assertEqual(len(self.dispatched), 1)
        self.assertEqual(
            self.dispatched[0].data["lang"], "en-US")

    def test_matched_notification_carries_the_match_lang(self):
        # PIPELINE-1 9.2: the notification declares the language matched in.
        self._dispatch_in_en()
        self.assertEqual(len(self.matched), 1)
        self.assertEqual(
            self.matched[0].data["lang"], "en-US")


if __name__ == "__main__":
    unittest.main()
