import unittest

from lingua_franca.internal import load_language

from ovos_intent_plugin_adapt import AdaptExtractor
from ovos_plugin_manager.templates.intents import IntentMatch


class TestAdapt(unittest.TestCase):
    load_language("en-us")  # setup LF normalizer
    skill_id = "adapt.test"

    intents = AdaptExtractor()

    weather = ["weather"]
    hello = ["hey", "hello", "hi", "greetings"]
    name = ["name is"]
    joke = ["joke"]
    play = ["play"]
    say = ["say", "tell"]
    music = ["music", "jazz", "metal", "rock"]
    door = ["door", "doors"]
    light = ["light", "lights"]
    on = ["activate", "on", "engage", "open"]
    off = ["deactivate", "off", "disengage", "close"]

    intents.register_entity(skill_id, "weather", weather)
    intents.register_entity(skill_id, "hello", hello)
    intents.register_entity(skill_id, "name", name)
    intents.register_entity(skill_id, "joke", joke)
    intents.register_entity(skill_id, "door", door)
    intents.register_entity(skill_id, "lights", light)
    intents.register_entity(skill_id, "on", on)
    intents.register_entity(skill_id, "off", off)
    intents.register_entity(skill_id, "play", play)
    intents.register_entity(skill_id, "music", music)
    intents.register_entity(skill_id, "say", say)

    intents.register_keyword_intent(skill_id, "weather", ["weather"], ["say"])
    intents.register_keyword_intent(skill_id, "hello", ["hello"])
    intents.register_keyword_intent(skill_id, "name", ["name"])
    intents.register_keyword_intent(skill_id, "joke", ["joke"], ["say"])
    intents.register_keyword_intent(skill_id, "lights_on", ["lights", "on"])
    intents.register_keyword_intent(skill_id, "lights_off", ["lights", "off"])
    intents.register_keyword_intent(skill_id, "door_open", ["door", "on"])
    intents.register_keyword_intent(skill_id, "door_close", ["door", "off"])
    intents.register_keyword_intent(skill_id, "play_music", ["play", "music"])

    engine = intents

    def test_base_intents(self):
        # validate utterance that will be part of other tests

        def test_intent(sent, intent_type):
            res = self.engine.calc_intent(sent)
            assert isinstance(res, IntentMatch)
            self.assertEqual(res.intent_service, "adapt")
            self.assertEqual(res.intent_type, intent_type)

        test_intent("tell me a joke", "joke")
        test_intent("say hello", "hello")
        test_intent("tell me the weather", "weather")
        test_intent("open the door", "door_open")
        test_intent("close the door", "door_close")
        test_intent("turn off the lights", "lights_off")
        test_intent("turn on the lights", "lights_on")
        test_intent("play some music", "play_music")

    def test_single_intent(self):
        # get intent from utterance mycroft style
        # 1 utterance -> 1 intent

        def test_intent(sent, intent_type, remainder):
            res = self.engine.calc_intent(sent)
            assert isinstance(res, IntentMatch)
            self.assertEqual(res.intent_service, "adapt")
            self.assertEqual(res.intent_type, intent_type)
            self.assertEqual(res.utterance_remainder, remainder)
            self.assertTrue(res.confidence <= 0.5)

        # multiple known intents in utterance
        # TODO Remainder is imperfect due to normalization, but let it pass for now
        test_intent("tell me a joke and say hello", "joke", 'me and say hello')
        test_intent("tell me a joke and the weather", "weather", 'me joke and')
        test_intent("close the door turn off the lights", "lights_off", 'door turn off')
        test_intent("close the pod bay doors play some music", "door_close", 'pod bay play some music')

        # known + unknown intents in utterance
        test_intent("tell me a joke order some pizza", "joke", 'me order some pizza')

        # unknown intents
        test_intent("Call mom tell her hello", "hello", 'Call mom tell her')  # "hello" intent is closest match
        test_intent("nice work! get me a beer", "unknown", 'nice work! get me beer')  # no intent at all

        # conflicting/badly modeled intents
        test_intent("turn off the lights, open the door", "lights_on", 'turn off , door')  # "open" and "off" conflict
        test_intent("turn on the lights close the door", "lights_on", 'turn close door')  # "on" and "close" conflict

    def test_main_secondary_intent(self):
        # get intent -> get intent from utt remainder
        # 1 utterance -> 2 intents

        def test_intent(sent, intents):
            res = self.engine.intent_remainder(sent)

            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "adapt"}
            else:
                first, second = res[0], res[1]

            self.assertEqual(first["intent_engine"], "adapt")
            self.assertEqual(second["intent_engine"], "adapt")

            self.assertEqual({first["intent_type"], second["intent_type"]}, set(intents))

        # multiple known intents in utterance
        test_intent("tell me a joke and say hello", {"joke", 'hello'})
        test_intent("tell me a joke and the weather", {"weather", 'joke'})
        test_intent("close the door turn off the lights", {'door_close', 'lights_off'})
        test_intent("close the pod bay doors play some music", {'play_music', 'door_close'})

        # known + unknown intents in utterance
        test_intent("tell me a joke order some pizza", {'joke', 'unknown'})

        # unknown intents
        test_intent("Call mom tell her hello", {'unknown', 'hello'})  # "hello" intent is closest match
        test_intent("nice work! get me a beer", {'unknown', 'unknown'})  # no intent at all

        # conflicting/badly modeled intents
        test_intent("turn off the lights, open the door", {'lights_on', 'door_close'})  # "open" and "off" conflict
        test_intent("turn on the lights close the door", {'door_close', 'lights_on'})  # "on" and "close" conflict

    def test_intent_list(self):
        # segment utterance -> calc intent
        # 1 utterance -> N intents
        # segmentation can get any number of sub-utterances
        # each sub-utterance can have 1 intent

        def test_intent(sent, expected):
            res = self.engine.calc_intents_list(sent)
            expected_segments = expected.keys()
            self.assertEqual(set(res.keys()), set(expected_segments))
            for utt, intents in expected.items():
                utt_intents = [i["intent_type"] for i in res[utt]]
                self.assertEqual(intents, utt_intents)

        # multiple known intents in utterance
        test_intent("tell me a joke and say hello",
                    {'say hello': ["hello"], 'tell me a joke': ["joke"]})
        test_intent("tell me a joke and the weather",
                    {'the weather': ['weather'], 'tell me a joke': ["joke"]})

        # unknown intents
        test_intent("nice work! get me a beer",
                    {'get me a beer': ["unknown"], 'nice work': ["unknown"]})

        # conflicting/badly modeled intents -> no conflict due to good segmentation
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': ["lights_off"], 'open the door': ["door_open"]})

        # failed segmentation (no markers to split)
        test_intent("close the door turn off the lights",
                    {'close the door turn off the lights': ["lights_off"]})
        test_intent("close the pod bay doors play some music",
                    {'close the pod bay doors play some music': ["door_close"]})

        # known + unknown intents in utterance + failed segmentation
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': ["joke"]})
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': ["hello"]})  # "hello" intent is closest match

        # conflicting/badly modeled intents -> conflict due to failed segmentation
        # NOTE: this one works by coincidence basically, could easily be door_open and lights_off
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': ["lights_on"]})  # "on" and "close" conflict

    def test_segment_main_secondary_intent(self):
        # segment -> get intent -> get intent from utt remainder
        # 1 utterance -> N intents
        # segmentation can get any number of sub-utterances
        # each sub-utterance can have 2 intents

        def test_intent(sent, expected, min_conf=0.5):
            for res in self.engine.intents_remainder(sent):
                if res["conf"] < min_conf:
                    continue
                utt = res["utterance"]
                self.assertEqual(res["intent_engine"], "adapt")
                self.assertIn(utt, expected)
                self.assertEqual(res["intent_type"], expected[utt])

        # multiple known intents in utterance
        test_intent("tell me a joke and say hello",
                    {'say hello': "hello", 'tell me joke': "joke"})
        test_intent("tell me a joke and the weather",
                    {'weather': 'weather', 'tell me joke': "joke"})

        # unknown intents
        test_intent("nice work! get me a beer",
                    {'get me beer': "unknown", 'nice work': "unknown"})

        # conflicting/badly modeled intents -> no conflict due to good segmentation
        test_intent("turn off the lights, open the door",
                    {'turn off lights': "lights_off", 'open door': "door_open"})

        # failed segmentation (no markers to split)
        test_intent("close the door turn off the lights",
                    {'close door turn off lights': "lights_off",
                     'door turn off': "door_close"})
        test_intent("close the pod bay doors play some music",
                    {'close pod bay doors play some music': "door_close"})

        # known + unknown intents in utterance + failed segmentation
        test_intent("tell me a joke order some pizza",
                    {'tell me joke order some pizza': "joke"})
        test_intent("Call mom tell her hello",
                    {'Call mom tell her hello': "hello"})  # "hello" intent is closest match

        # conflicting/badly modeled intents -> conflict due to failed segmentation
        # NOTE: this one works by coincidence basically, could easily be door_open and lights_off
        test_intent("turn on the lights close the door",
                    {'turn on the lights': "lights_on",
                     'turn close door': "door_close"})  # "on" and "close" conflict
