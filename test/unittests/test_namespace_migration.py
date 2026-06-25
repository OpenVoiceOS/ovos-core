"""Namespace-migration dedup tests for the utterance entry.

During the bus-namespace migration producers dual-emit the utterance entry on
the legacy ``recognizer_loop:utterance`` and the new ``ovos.utterance.handle``
(OVOS-PIPELINE-1 §9.1) topics. IntentService listens on both, so the same
content arriving on both topics within the dedup window must be handled once.
"""
import unittest
from unittest.mock import Mock

from ovos_bus_client.message import Message
from ovos_bus_client.util import Deduplicator

from ovos_core.intent_services import IntentService


class TestUtteranceDedup(unittest.TestCase):

    def setUp(self):
        # build a bare IntentService without loading the heavy pipelines;
        # exercise only the dedup guard at the top of handle_utterance
        self.service = IntentService.__new__(IntentService)
        self.service._utt_dedup = Deduplicator()
        # short-circuit handle_utterance right after the dedup guard so the
        # test counts how many times processing proceeds past it
        self._processed = []
        self.service._handle_transformers = Mock(
            side_effect=lambda m: self._processed.append(m) or m)
        # _handle_transformers returns a message whose context lacks "canceled",
        # then disambiguate_lang etc. would run; raise to stop right after.
        self.service.disambiguate_lang = Mock(side_effect=RuntimeError("stop"))

    def _emit(self, msg_type):
        msg = Message(msg_type, {"utterances": ["hello world"], "lang": "en-US"})
        try:
            self.service.handle_utterance(msg)
        except RuntimeError:
            pass  # expected: we stop right after the dedup guard

    def test_dual_emit_handled_once(self):
        # same utterance arrives on both namespaces within the window
        self._emit("recognizer_loop:utterance")
        self._emit("ovos.utterance.handle")
        # processed exactly once; the second (duplicate) was dropped
        self.assertEqual(len(self._processed), 1)

    def test_distinct_utterances_both_handled(self):
        msg1 = Message("recognizer_loop:utterance",
                       {"utterances": ["turn on the lights"], "lang": "en-US"})
        msg2 = Message("ovos.utterance.handle",
                       {"utterances": ["what time is it"], "lang": "en-US"})
        for m in (msg1, msg2):
            try:
                self.service.handle_utterance(m)
            except RuntimeError:
                pass
        self.assertEqual(len(self._processed), 2)

    def test_same_text_different_lang_both_handled(self):
        # lang is part of the dedup key, so the same text in two langs is distinct
        msg1 = Message("recognizer_loop:utterance",
                       {"utterances": ["hello world"], "lang": "en-US"})
        msg2 = Message("ovos.utterance.handle",
                       {"utterances": ["hello world"], "lang": "pt-PT"})
        for m in (msg1, msg2):
            try:
                self.service.handle_utterance(m)
            except RuntimeError:
                pass
        self.assertEqual(len(self._processed), 2)


if __name__ == "__main__":
    unittest.main()
