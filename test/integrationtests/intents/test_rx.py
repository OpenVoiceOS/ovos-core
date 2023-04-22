import unittest

from lingua_franca.internal import load_language

from ovos_intent_plugin_regex import RegexExtractor


class TestRegex(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        load_language("en-us")  # setup LF normalizer

        intents = RegexExtractor()
        play = ["^play (?P<Music>.+)$"]
        location = [".*(at|in) (?P<Location>.+)$"]
        intents.register_regex_intent("play", play)
        intents.register_regex_entity("Location", location)

        self.engine = intents

    def test_regex_entity(self):

        def test_entities(sent, entities):
            res = self.engine.extract_regex_entities(sent)
            self.assertEqual(res, entities)

        test_entities("bork the zork", {})
        test_entities("how is the weather in Paris", {'Location': 'paris'})

    def test_regex_intent(self):
        # get intent from utterance mycroft style
        # 1 utterance -> 1 intent

        def test_intent(sent, intent, entities=None, min_conf=0.0):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "regex")
            self.assertIn(res["intent_type"], intent)
            if entities:
                self.assertEqual(res["entities"], entities)

        test_intent("play metallica", 'play', entities={'Music': 'metallica'})
        test_intent("play", 'unknown')
        test_intent("bork the zork", 'unknown')
