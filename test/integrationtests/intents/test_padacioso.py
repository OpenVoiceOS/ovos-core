import unittest

from lingua_franca.internal import load_language

from neon_intent_plugin_padacioso import PadaciosoExtractor


class TestPadacioso(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        load_language("en-us")  # setup LF normalizer

        intents =  PadaciosoExtractor()

        weather = ["weather", "the weather"]
        hello = ["hey", "hello", "hi", "greetings"]
        name = ["my name is {name}"]
        joke = ["tell me a joke", "i want a joke", "say a joke", "tell joke"]
        lights_on = ["turn on the lights", "lights on", "turn lights on",
                     "turn the lights on"]
        lights_off = ["turn off the lights", "lights off", "turn lights off",
                      "turn the lights off"]
        door_on = ["open the door", "open door", "open the doors"]
        door_off = ["close the door", "close door", "close the doors"]
        music = ["play music", "play some songs", "play heavy metal",
                 "play some jazz", "play rock", "play some music"]
        pizza = ["order pizza", "get pizza", "buy pizza"]
        call = ["call {person}", "phone {person}"]
        greet_person = ["say hello to {person}", "tell {person} hello",
                        "tell {person} i said hello"]

        intents.register_intent("weather", weather)
        intents.register_intent("hello", hello)
        intents.register_intent("name", name)
        intents.register_intent("joke", joke)
        intents.register_intent("lights_on", lights_on)
        intents.register_intent("lights_off", lights_off)
        intents.register_intent("door_open", door_on)
        intents.register_intent("door_close", door_off)
        intents.register_intent("play_music", music)
        intents.register_intent("pizza", pizza)
        intents.register_intent("greet_person", greet_person)
        intents.register_intent("call_person", call)

        self.engine = intents

    def test_single_intent(self):
        # get intent from utterance mycroft style
        # 1 utterance -> 1 intent

        def test_intent(sent, intent, entities=None, min_conf=0.0):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "padacioso")
            self.assertIn(res["intent_type"], intent)
            if entities:
                self.assertEqual(res["entities"], entities)

        def test_intent_fail(sent, min_conf=0.0):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "padacioso")
            self.assertIn(res["intent_type"], "unknown")
            self.assertIn(res["utterance_remainder"], sent)

        # expected matches
        test_intent("Call mom tell her hello", 'call_person', entities={'person': 'mom tell her hello'})
        test_intent("tell me a joke and say hello", "greet_person", entities={'person': 'me a joke and say'})

        # failed intents
        test_intent_fail("close the door turn off the lights")
        test_intent_fail("close the pod bay doors play some music")
        test_intent_fail("turn off the lights, open the door")
        test_intent_fail("turn on the lights close the door")
        test_intent_fail("tell me a joke and the weather")
        test_intent_fail("tell me a joke and the weather")
        test_intent_fail("tell me a joke order some pizza")
        test_intent_fail(
            "tell me a joke and order some pizza and turn on the lights and close the door and play some songs")

        # unknown intents
        test_intent_fail("nice work! get me a beer")

    def test_main_secondary_intent(self):
        # get intent -> get intent from utt remainder
        # 1 utterance -> 2 intents

        def test_intent(sent, intent, entities=None):
            res = self.engine.intent_remainder(sent)
            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "padacioso"}
            else:
                first, second = res[0], res[1]

            self.assertEqual(first["intent_engine"], "padacioso")
            self.assertEqual(second["intent_engine"], "padacioso")

            self.assertEqual(first["intent_type"], intent)
            self.assertEqual(second["intent_type"], "unknown")

            if entities:
                self.assertEqual(first["entities"], entities)

        def test_intent_fail(sent):
            res = self.engine.intent_remainder(sent)[0]
            self.assertEqual(res["intent_engine"], "padacioso")
            self.assertEqual(res["intent_type"], "unknown")

        test_intent("Call mom tell her hello", "call_person", entities={'person': 'mom tell her hello'})
        test_intent("tell me a joke and say hello", "greet_person", entities={'person': 'me a joke and say'})

        # failed intents
        test_intent_fail("close the door turn off the lights")
        test_intent_fail("close the pod bay doors play some music")
        test_intent_fail("turn off the lights, open the door")
        test_intent_fail("turn on the lights close the door")
        test_intent_fail("tell me a joke order some pizza")
        test_intent_fail("tell me a joke and the weather")

        # unknown intents
        test_intent_fail("nice work! get me a beer")

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

        # good segmentation
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': ["lights_off"], 'open the door': ["door_open"]})
        test_intent("hello, tell me a joke",
                    {'hello': ["hello"], 'tell me a joke': ["joke"]})
        test_intent("tell me a joke and the weather",
                    {'the weather': ["weather"], 'tell me a joke': ["joke"]})

        # unknown intents
        test_intent("nice work! get me a beer",
                    {'get me a beer': ["unknown"], 'nice work': ["unknown"]})

        # failed segmentation (no markers to split)
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': ["unknown"]})
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': ['call_person']})
        test_intent("close the door turn off the lights",
                    {'close the door turn off the lights': ["unknown"]})
        test_intent("close the pod bay doors play some music",
                    {'close the pod bay doors play some music': ["unknown"]})
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': ["unknown"]})

    def test_segment_main_secondary_intent(self):
        # segment -> get intent -> get intent from utt remainder
        # 1 utterance -> N intents
        # segmentation can get any number of sub-utterances
        # each sub-utterance can have 2 intents

        def test_intent(sent, expected, entities=None):
            entities = entities or {}
            for res in self.engine.intents_remainder(sent):
                if res["intent_type"] == "unknown" and res["utterance"] not in expected:
                    continue
                utt = res["utterance"]
                self.assertEqual(res["intent_engine"], "padacioso")
                self.assertIn(res["utterance"], expected)
                self.assertEqual(res["intent_type"], expected[utt])
                if utt in entities:
                    self.assertEqual(entities[utt], res["entities"])

        def test_intent_fail(sent, min_conf=0.0):
            for res in self.engine.intents_remainder(sent):
                self.assertEqual(res["intent_engine"], "padacioso")
                self.assertIn(res["intent_type"], "unknown")
                self.assertIn(res["utterance_remainder"], sent)

        # good segmentation
        test_intent("tell me a joke and say hello",
                    {'say hello': "unknown",
                     'tell me a joke': "joke"})
        test_intent("tell me a joke and the weather",
                    {'the weather': 'weather',
                     'tell me a joke': "joke"})
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': "lights_off",
                     'open the door': "door_open"})

        # failed segmentation (no markers to split)
        test_intent_fail("close the door turn off the lights")
        test_intent_fail("close the pod bay doors play some music")
        test_intent_fail("tell me a joke order some pizza")
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': "call_person"},
                    entities={'mom tell {person} hello': {"person": "her"}})
        test_intent_fail("turn on the lights close the door")
