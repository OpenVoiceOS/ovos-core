"""Guard for the post-compat world: nothing bridges the legacy bus namespace.

The sibling end-to-end modules used to run every scenario twice — once
injecting the utterance on the spec topic, once on the legacy
``recognizer_loop:utterance`` — because the bus bridged the two. The bridge is
gone, so those files now run the spec path only and this module pins the other
half: injecting on the legacy topic reaches nothing, and the pipeline emits no
legacy twin of its own.

Unit-level coverage of the bridge removal lives in ovos-bus-client
(``test_no_legacy_wire_compat.py``) and ovos-utils
(``test_fakebus_no_legacy_compat.py``). This module proves the same thing
through a real MiniCroft boot, where a surviving bridge in any layer of the
stack would still show up.
"""
import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import get_minicroft

SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value
LEGACY_UNMATCHED = migration_counterpart(INTENT_UNMATCHED)


class TestNoLegacyWireCompat(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.minicroft = get_minicroft([])

    def tearDown(self):
        LOG.set_level("CRITICAL")
        self.minicroft.stop()

    def _capture(self, *topics):
        seen = []
        for topic in topics:
            self.minicroft.bus.on(topic, lambda m: seen.append(m.msg_type))
        return seen

    def _session_message(self, topic):
        session = Session("123")
        session.lang = "en-US"
        return Message(topic,
                       {"utterances": ["hello world"], "lang": session.lang},
                       {"session": session.serialize(),
                        "source": "A", "destination": "B"})

    def test_legacy_utterance_topic_starts_no_pipeline(self):
        """The orchestrator listens on the spec topic only."""
        seen = self._capture(INTENT_UNMATCHED, UTTERANCE_HANDLED)
        self.minicroft.bus.emit(self._session_message(LEGACY_UTTERANCE))
        time.sleep(2)
        self.assertEqual(seen, [])

    def test_spec_utterance_topic_still_runs_the_pipeline(self):
        """The control: the same injection on the spec topic works."""
        seen = self._capture(INTENT_UNMATCHED, UTTERANCE_HANDLED)
        self.minicroft.bus.emit(self._session_message(SPEC_UTTERANCE))
        time.sleep(2)
        self.assertIn(INTENT_UNMATCHED, seen)
        self.assertIn(UTTERANCE_HANDLED, seen)

    def test_no_match_emits_no_legacy_twin(self):
        """OVOS-PIPELINE-1 §9.3 no-match emits ovos.intent.unmatched alone.

        ``complete_intent_failure`` used to ride along on the emit_legacy
        bridge. A consumer still subscribed to it now hears nothing.
        """
        legacy_seen = self._capture(LEGACY_UNMATCHED)
        spec_seen = self._capture(INTENT_UNMATCHED)
        self.minicroft.bus.emit(self._session_message(SPEC_UTTERANCE))
        time.sleep(2)
        self.assertIn(INTENT_UNMATCHED, spec_seen)
        self.assertEqual(legacy_seen, [])
