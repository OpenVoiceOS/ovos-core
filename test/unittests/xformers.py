import unittest
from copy import deepcopy
from unittest.mock import Mock

from ovos_core.transformers import UtteranceTransformersService
from ovos_plugin_manager.templates.transformers import UtteranceTransformer

from ovos_utils.fakebus import FakeBus


class MockTransformer(UtteranceTransformer):

    def __init__(self):
        super().__init__("mock_transformer")

    def transform(self, utterances, context=None):
        return utterances + ["transformer"], {}


class MockContextAdder(UtteranceTransformer):

    def __init__(self):
        super().__init__("mock_context_adder")

    def transform(self, utterances, context=None):
        return utterances, {"old_context": False,
                            "new_context": True,
                            "new_key": "test"}


class TextTransformersTests(unittest.TestCase):
    def test_utterance_transformer_service_load(self):
        bus = FakeBus()
        service = UtteranceTransformersService(bus)
        self.assertIsInstance(service.config, dict)
        self.assertEqual(service.bus, bus)
        self.assertFalse(service.has_loaded)
        self.assertIsInstance(service.loaded_plugins, dict)
        for plugin in service.loaded_plugins:
            self.assertIsInstance(service.loaded_plugins[plugin],
                                  UtteranceTransformer)
        self.assertIsInstance(service.plugins, list)
        self.assertEqual(len(service.loaded_plugins), len(service.plugins))
        service.shutdown()

    def test_utterance_transformer_service_transform(self):
        bus = FakeBus()
        service = UtteranceTransformersService(bus)
        service.loaded_plugins = {"mock_transformer": MockTransformer()}
        utterances = ["test", "utterance"]
        context = {"old_context": True,
                   "new_context": False}
        utterances, context = service.transform(utterances, context)
        self.assertEqual(" ".join(utterances), "test utterance transformer")
        self.assertEqual(context, {"old_context": True,
                                   "new_context": False})

        service.loaded_plugins["mock_context_adder"] = MockContextAdder()
        utterances, context = service.transform(utterances, context)
        self.assertEqual(utterances, ["test", "utterance",
                                      "transformer", "transformer"])
        self.assertEqual(context, {"old_context": False,
                                   "new_context": True,
                                   "new_key": "test"})
        service.shutdown()

    def test_utterance_transformer_service_priority(self):

        utterances = ["test 1", "test one"]
        lang = "en-US"

        def mod_1_parse(utterances, lang):
            utterances.append("mod 1 parsed")
            return utterances, {"parser_context": "mod_1"}

        def mod_2_parse(utterances, lang):
            utterances.append("mod 2 parsed")
            return utterances, {"parser_context": "mod_2"}

        bus = FakeBus()
        service = UtteranceTransformersService(bus)

        mod_1 = Mock()
        mod_1.priority = 2
        mod_1.transform = mod_1_parse
        mod_2 = Mock()
        mod_2.priority = 1
        mod_2.transform = mod_2_parse

        service.loaded_plugins = \
            {"test_mod_1": mod_1,
             "test_mod_2": mod_2}

        # Check transformers adding utterances
        new_utterances, context = service.transform(deepcopy(utterances),
                                                    {'lang': lang})
        self.assertEqual(context["parser_context"], "mod_2")
        self.assertNotEqual(new_utterances, utterances)
        self.assertEqual(len(new_utterances),
                         len(utterances) + 2)

        # Check context change on priority swap
        mod_2.priority = 100
        _, context = service.transform(deepcopy(utterances),
                                       {'lang': lang})
        self.assertEqual(context["parser_context"], "mod_1")


if __name__ == "__main__":
    unittest.main()
