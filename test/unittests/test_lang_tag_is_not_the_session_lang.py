"""A per-utterance language tag must not become the session language.

Reported from the field: an nl-NL install answers in English after a media
request, and stays English. An English song title makes a language detector tag
one utterance ``en``; the resolver then wrote that tag onto the DEFAULT session
and core broadcast its store, so every later untagged utterance resolved en-US
from the poisoned store.

OVOS-SESSION-1 §3.2.7 governs the act:

    Resolution reads the signals; it MUST NOT mutate them.

    The resolved tag MUST travel with the utterance so that every downstream
    consumer reads the same value.

and §3.2.1 defines the field it was written to:

    lang is stable across the session, not derived from any one utterance.

``detected_lang`` and ``stt_lang`` are the per-utterance observations the
resolver reads (§3.2, "one purpose per field, no overlaps"); ``session.lang``
is the preference declared by the session origin.

This pins the RESOLVER only. OVOS-TRANSFORM-1 §7.1 still lets an utterance
transformer overwrite ``session.lang`` when a confident classification warrants
persisting it, so the assertion here is "the resolver did not write it", never
"the field cannot be written".
"""
import unittest
import unittest.mock
from collections import defaultdict
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.service import IntentService


def _service(bus, valid_langs) -> IntentService:
    """A real IntentService with the real disambiguate_lang, no pipelines."""
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.status = MagicMock()
    for attr, transform in (("utterance_plugins", lambda utt, ctx: (utt, ctx)),
                            ("metadata_plugins", lambda ctx: ctx),
                            ("intent_plugins", lambda intent: intent)):
        plugins = MagicMock()
        plugins.transform.side_effect = transform
        setattr(svc, attr, plugins)
    typed_slots = MagicMock()
    typed_slots.transform.return_value = None
    svc.typed_slots_plugins = typed_slots
    svc.intent_manifest = IntentManifest(bus)
    svc.intent_dispatcher = IntentDispatcher(
        bus, timeout=0, on_terminal=svc._emit_utterance_handled)
    svc.get_pipeline = lambda session: []
    return svc


class TestATagDoesNotBecomeTheSessionLanguage(unittest.TestCase):

    VALID = ["nl-NL", "en-US"]

    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None
        store = SessionManager.get_default_session()
        store.lang = "nl-NL"
        self.svc = _service(self.bus, self.VALID)
        # en-US is a valid language on this install, as secondary_langs makes it
        self._patch = unittest.mock.patch(
            "ovos_core.intent_services.service.get_valid_languages",
            return_value=list(self.VALID))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()

    def _drive(self, message):
        handled = []
        self.bus.on(SpecMessage.UTTERANCE_HANDLED, handled.append)
        self.svc.handle_utterance(message)
        self.bus.remove(SpecMessage.UTTERANCE_HANDLED, handled.append)
        return handled

    def _tagged(self, tag_field, tag):
        return Message("recognizer_loop:utterance",
                       data={"utterances": ["play bohemian rhapsody"]},
                       context={tag_field: tag})

    def _untagged(self):
        """The next turn, carrying no tag and no lang of its own.

        It carries the default-session carrier, which is what every
        ``MessageBusClient.emit`` stamps, so resolution reaches the
        orchestrator's store rather than this test process's configuration:
        ``get_message_lang`` consults the session only when the message has a
        carrier, and falls back to the deployment default otherwise (which on
        the reporter's install is nl-NL and in a test process is not).
        """
        return Message("recognizer_loop:utterance",
                       data={"utterances": ["hoe laat is het"]},
                       context={"session": {"session_id": "default"}})

    def test_detected_lang_does_not_move_the_store(self):
        self._drive(self._tagged("detected_lang", "en-US"))
        self.assertEqual(SessionManager.get_default_session().lang, "nl-NL")

    def test_stt_lang_does_not_move_the_store(self):
        self._drive(self._tagged("stt_lang", "en"))
        self.assertEqual(SessionManager.get_default_session().lang, "nl-NL")

    def test_the_next_untagged_utterance_runs_in_the_session_language(self):
        """The reporter's actual complaint: not the English answer to the
        English title, but every Dutch sentence after it."""
        self._drive(self._tagged("detected_lang", "en-US"))
        second = self._untagged()
        self._drive(second)
        self.assertEqual(second.data.get("lang"), "nl-NL")
        self.assertEqual(SessionManager.get_default_session().lang, "nl-NL")

    def test_the_store_is_what_the_second_turn_reads(self):
        """The control for the case above: with the store deliberately moved to
        en-US the same second turn resolves en-US, so that assertion is reading
        the store and not this process's configuration."""
        self._drive(self._tagged("detected_lang", "en-US"))
        store = SessionManager.get_default_session()
        store.lang = "en-US"
        SessionManager.update(store)
        second = self._untagged()
        self._drive(second)
        self.assertEqual(second.data.get("lang"), "en-US")

    def test_the_tag_still_travels_on_the_utterance_it_came_with(self):
        """§3.2.7: the resolved tag MUST travel with the utterance. Not writing
        the store must not mean losing the tag — the English title is still
        handled as English."""
        tagged = self._tagged("detected_lang", "en-US")
        self._drive(tagged)
        self.assertEqual(tagged.data.get("lang"), "en-US")

    def test_a_transformer_may_still_persist_a_classification(self):
        """OVOS-TRANSFORM-1 §7.1 keeps its permission: the control that stops
        this fix from being read as 'session.lang is immutable'."""
        store = SessionManager.get_default_session()
        store.lang = "en-US"          # as a transformer would persist it
        SessionManager.update(store)
        self.assertEqual(SessionManager.get_default_session().lang, "en-US")
        second = self._untagged()
        self._drive(second)
        self.assertEqual(second.data.get("lang"), "en-US",
                         "a persisted classification must still govern the "
                         "next utterance")


class TestAMatchedRoundDoesNotMoveTheStoreEither(unittest.TestCase):
    """The other half of the report, which this change alone did not fix.

    The reporter's utterance MATCHED: "speel bohemian rhapsody van queen" hit
    `ocp:play`. The resolver fix above covers the no-match path, and the
    reviewer's live cell showed the matched path still moving the store,
    because `_dispatch_match` held its own `sess.lang = lang` and for the
    default session `sess` IS the OVOS-SESSION-2 §5.1 store.

    That second writer was removed by #1018, now in `dev`. With both
    writers gone a tagged utterance that matches leaves the store alone, which
    is the state the reporter needs. This case exists so the suite reads the
    whole report rather than the half this branch owns: if either writer comes
    back, it fails.
    """

    VALID = ["nl-NL", "en-US"]

    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None
        SessionManager.get_default_session().lang = "nl-NL"
        self.svc = _service(self.bus, self.VALID)
        self._patch = unittest.mock.patch(
            "ovos_core.intent_services.service.get_valid_languages",
            return_value=list(self.VALID))
        self._patch.start()
        # one matcher that always matches, standing in for the OCP plugin the
        # reporter hit. What is under test is what the orchestrator does AFTER
        # a match, so any matcher carries the result.
        self.matched_langs = []

        def _always_match(utterances, lang, message):
            self.matched_langs.append(lang)
            return IntentHandlerMatch(match_type="ocp:play", match_data={},
                                      skill_id="ocp", utterance=utterances[0][0]
                                      if utterances and isinstance(utterances[0], (list, tuple))
                                      else "speel bohemian rhapsody van queen")

        self.svc.get_pipeline = lambda session: [("ocp-high", _always_match)]

    def tearDown(self):
        self._patch.stop()
        self.svc.intent_dispatcher.shutdown()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()

    def _drive(self, message):
        self.svc.handle_utterance(message)

    def _tagged(self):
        return Message("recognizer_loop:utterance",
                       data={"utterances": ["speel bohemian rhapsody van queen"]},
                       context={"detected_lang": "en-US"})

    def _untagged(self):
        return Message("recognizer_loop:utterance",
                       data={"utterances": ["hoe laat is het"]},
                       context={"session": {"session_id": "default"}})

    def test_the_control_the_round_really_matched(self):
        """Without this the assertions below could pass on a round that never
        reached the dispatch path at all."""
        self._drive(self._tagged())
        self.assertTrue(self.matched_langs,
                        "the stub matcher was never called")

    def test_a_tagged_matched_round_leaves_the_store(self):
        self._drive(self._tagged())
        self.assertEqual(SessionManager.get_default_session().lang, "nl-NL")

    def test_the_next_dutch_utterance_still_runs_dutch(self):
        """The reporter's complaint in one line: every Dutch sentence after
        the English title."""
        self._drive(self._tagged())
        second = self._untagged()
        self._drive(second)
        self.assertEqual(second.data.get("lang"), "nl-NL")
        self.assertEqual(SessionManager.get_default_session().lang, "nl-NL")

    def test_the_tag_still_governs_the_utterance_it_came_with(self):
        """§3.2.7: the resolved tag travels with its own utterance. The
        English title is still matched in English."""
        tagged = self._tagged()
        self._drive(tagged)
        self.assertEqual(tagged.data.get("lang"), "en-US")
        self.assertIn("en-US", self.matched_langs)


if __name__ == "__main__":
    unittest.main()
