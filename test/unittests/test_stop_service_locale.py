# Copyright 2024 OpenVoiceOS
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
"""Real-locale coverage for ``StopService``'s vocabulary matching.

Every existing test in ``test_stop_service.py`` builds the service with
``StopService.__new__(StopService)``, so ``__init__`` never runs and
``self._locale = LocaleResources(...)`` at stop_service.py never executes;
those tests then assign ``svc._locale = MagicMock()``, whose ``voc_match``
returns a truthy ``Mock`` for any input. That means the real matching path
through ``ovos_spec_tools.LocaleResources`` has no coverage in this repo at
all: a matcher that always returns true, or one that never loads a real
resource, would still pass every existing test. This module builds a real
``StopService`` with its real locale loader and checks real stop-word
matching, positive and negative, in three languages.
"""

import unittest

from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.stop_service import StopService
from ovos_spec_tools import LocaleResources


def _make_real_service() -> StopService:
    """Construct a StopService the normal way, with a FakeBus standing in
    for the real MessageBusClient. Nothing about locale construction is
    patched: ``__init__`` runs, and ``self._locale`` is built from the real
    ``ovos_core/intent_services/locale`` resource directory."""
    return StopService(bus=FakeBus())


class TestStopServiceRealLocale(unittest.TestCase):
    """Positive and negative stop-word matching against the real locale
    resources shipped in ``ovos_core/intent_services/locale``."""

    def test_real_locale_resources_are_constructed(self):
        svc = _make_real_service()
        self.assertIsInstance(svc._locale, LocaleResources)

    # -- positive matches, one real stop utterance per language, taken
    #    verbatim from the shipped .voc files --

    def test_stop_matches_en_us(self):
        svc = _make_real_service()
        # ovos_core/intent_services/locale/en-us/stop.voc, line 1
        self.assertTrue(svc._locale.voc_match("stop", "stop", "en-US", exact=True))

    def test_stop_matches_de_de(self):
        svc = _make_real_service()
        # ovos_core/intent_services/locale/de-de/stop.voc: "stoppe das"
        self.assertTrue(svc._locale.voc_match("stoppe das", "stop", "de-DE", exact=True))

    def test_stop_matches_pt_pt(self):
        svc = _make_real_service()
        # ovos_core/intent_services/locale/pt-pt/stop.voc: "(pára|pare)"
        self.assertTrue(svc._locale.voc_match("pára", "stop", "pt-PT", exact=True))

    # -- negative matches: an ordinary utterance that is not a stop word
    #    must NOT match. A matcher that returns true unconditionally (as a
    #    MagicMock does) would fail every one of these. --

    def test_non_stop_utterance_does_not_match_en_us(self):
        svc = _make_real_service()
        self.assertFalse(
            svc._locale.voc_match("what is the weather today", "stop", "en-US", exact=True))

    def test_non_stop_utterance_does_not_match_de_de(self):
        svc = _make_real_service()
        self.assertFalse(
            svc._locale.voc_match("wie ist das wetter heute", "stop", "de-DE", exact=True))

    def test_non_stop_utterance_does_not_match_pt_pt(self):
        svc = _make_real_service()
        self.assertFalse(
            svc._locale.voc_match("como esta o tempo hoje", "stop", "pt-PT", exact=True))


if __name__ == '__main__':
    unittest.main()
