import unittest

from lingua_franca.internal import load_language

from ovos_intent_plugin_padatious import PadatiousExtractor


class TestPadatious(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        load_language("en-us")  # setup LF normalizer

        intents = PadatiousExtractor()

        weather = ["weather"]
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

        # NOTE: padatious is not deterministic
        # the same utterance will sometimes get you a different intent
        # this is particularly bad in these tests that contain multiple intents in a single utterance
        # these tests accept any of the "valid" predictions to manage this

        def test_intent(sent, valid_intent_types, valid_remainders, min_conf=0.0):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "padatious")
            self.assertIn(res["intent_type"], valid_intent_types)
            self.assertIn(res["utterance_remainder"], valid_remainders)

        # multiple known intents in utterance
        # TODO Remainder is an imperfect heuristic, but let it pass for now
        test_intent("tell me a joke and say hello",
                    ["greet_person", "joke"], ['me a joke and'])
        test_intent("close the door turn off the lights",
                    ["lights_off", "door_close"], ['close door', 'turn off lights'])
        test_intent("close the pod bay doors play some music",
                    ["door_close", "play_music"], ['close the pod bay doors', 'pod bay play some music'])
        test_intent("Call mom tell her hello",
                    ["greet_person", 'call_person'], ['mom tell her hello'])
        test_intent("turn off the lights, open the door",
                    ["lights_off", 'door_open'], ['turn off lights ,', ', open door'])
        test_intent("turn on the lights close the door",
                    ["lights_on", 'door_close'], ['turn on lights', 'close door'])

        # unknown intents
        # TODO - seems like we occasionally get low confidence matches to other intents
        test_intent("nice work! get me a beer", ["unknown"], ['nice work! get me a beer'], min_conf=0.5)

        # conflicting intents
        # TODO, sometimes these select greet_person, this is because of "tell {person}" and "tell me a joke"
        test_intent("tell me a joke and the weather",
                    ["joke", 'greet_person', "weather"],
                    ['and the weather', 'me a joke and the weather', 'tell me a joke and the'])
        test_intent("tell me a joke order some pizza",
                    ["joke", "pizza", "greet_person"],
                    ['order some pizza', 'tell me a joke some', 'me a joke order some pizza'])
        test_intent("tell me a joke and order some pizza and turn on the lights and close the door and play some songs",
                    ["joke", 'greet_person', 'play_music', 'pizza', 'lights_on', "door_close"],
                    ['me a joke and order some pizza and turn on the lights and close the door and play some songs',
                     'tell me a joke and order some pizza and and close door and play some songs',
                     'tell me a joke and order pizza and turn on the lights and close the door and',
                     'tell me a joke and order some pizza and turn on lights and and play some songs',
                     'tell me a joke and some and turn on the lights and close the door and play some songs',
                     'and order some pizza and turn on the lights and close the door and play some songs'])

    def test_main_secondary_intent(self):
        # get intent -> get intent from utt remainder
        # 1 utterance -> 2 intents

        def test_intent(sent, intents):
            res = self.engine.intent_remainder(sent)

            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "padatious"}
            else:
                first, second = res[0], res[1]

            self.assertEqual(first["intent_engine"], "padatious")
            self.assertEqual(second["intent_engine"], "padatious")

            self.assertEqual({first["intent_type"], second["intent_type"]}, set(intents))

        def test_ambiguous(sent, expected1, expected2=None):
            expected2 = expected2 or ["unknown"]
            res = self.engine.intent_remainder(sent)
            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "padatious"}
            else:
                first, second = res[0], res[1]
            self.assertIn(first["intent_type"], expected1)
            self.assertIn(second["intent_type"], expected2)

        # multiple known intents in utterance
        test_intent("close the door turn off the lights", {'door_close', 'lights_off'})
        test_intent("close the pod bay doors play some music", {'play_music', 'door_close'})
        test_intent("turn off the lights, open the door", {'lights_off', 'door_open'})
        test_intent("turn on the lights close the door", {'door_close', 'lights_on'})
        test_intent("Call mom tell her hello", {'call_person', 'greet_person'})

        # unknown intents
        test_intent("nice work! get me a beer", {'unknown', 'unknown'})  # no intent at all

        # conflicting intents/badly modeled intents
        # TODO, sometimes these select greet_person, this is because of "tell {person}" and "tell me a joke"
        # not determinstic, sometimes pass sometimes fails
        test_ambiguous("tell me a joke and say hello",
                       ["joke", "greet_person"],
                       ['hello', "joke"]  # say hello often returns no intent
                       )
        test_ambiguous("tell me a joke order some pizza",  ["joke", "pizza", 'greet_person'], ["pizza", "joke"])
        test_ambiguous("tell me a joke and the weather",  ["joke", 'greet_person'],  ["weather", "joke"])

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

        def test_ambiguous(sent, expected):
            res = self.engine.calc_intents_list(sent)
            for utt, intents in expected.items():
                for i in res[utt]:
                    self.assertIn(i["intent_type"], intents)

        # multiple known intents in utterance
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': ["lights_off"], 'open the door': ["door_open"]})

        # unknown intents
        test_intent("nice work! get me a beer",
                    {'get me a beer': ["unknown"], 'nice work': ["unknown"]})

        # conflicting intents/badly modeled intents
        # TODO, sometimes these select greet_person, this is because of "tell {person}" and "tell me a joke"
        # not determinstic, sometimes pass sometimes fails
        test_ambiguous("hello, tell me a joke",
                       {'hello': ["hello"], 'tell me a joke': ["joke", "greet_person"]})
        test_ambiguous("tell me a joke and the weather",
                       {'the weather': ['weather'], 'tell me a joke': ["joke", "greet_person"]})
        test_ambiguous("tell me a joke order some pizza",
                       {'tell me a joke order some pizza': ["joke", "pizza", "greet_person"]})

        # failed segmentation (no markers to split)
        test_ambiguous("call mom tell her hello",
                       {'call mom tell her hello': ['greet_person', 'call_person', "hello"]})
        test_ambiguous("close the door turn off the lights",
                       {'close the door turn off the lights': ["lights_off", "door_close"]})
        test_ambiguous("close the pod bay doors play some music",
                       {'close the pod bay doors play some music': ["door_close", "play_music"]})
        test_ambiguous("turn on the lights close the door",
                       {'turn on the lights close the door': ["lights_on", "door_close"]})

    def test_segment_main_secondary_intent(self):
        # segment -> get intent -> get intent from utt remainder
        # 1 utterance -> N intents
        # segmentation can get any number of sub-utterances
        # each sub-utterance can have 2 intents

        def test_intent(sent, expected, entities=None):
            entities = entities or {}
            for res in self.engine.intents_remainder(sent):
                if res["intent_type"] == "unknown" or res["conf"] < 0.5:
                    continue
                utt = res["utterance"]
                self.assertEqual(res["intent_engine"], "padatious")
                self.assertIn(res["utterance"], expected)
                self.assertIn(res["intent_type"], expected[utt])
                if utt in entities:
                    self.assertEqual(entities[utt], res["entities"])

        # good segmentation with clean known intents
        test_intent("tell me a joke and say hello",
                    {'say hello': ["hello"], 'tell me a joke': ["joke"]})
        test_intent("tell me a joke and the weather",
                    {'the weather': ['weather'], 'tell me a joke': ["joke"]})
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': ["lights_off"], 'open the door': ["door_open"]})

        # failed segmentation (no markers to split)
        # depending on intent for unsegmented utterance,
        # a different utterance remainder will ensure the missing intent also matches
        test_intent("close the door turn off the lights",
                    {'close the door turn off the lights': ["lights_off", "door_close"],
                     "close door": ["door_close"],
                     'turn off lights': ["lights_off"]})
        test_intent("close the pod bay doors play some music",
                    {'close the pod bay doors play some music': ["door_close", "play_music"],
                     'close the pod bay doors': ["door_close"],
                     'pod bay play some music': ["play_music"]})
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': ["joke", "pizza"],
                     'order some pizza': ["pizza"],
                     'me a joke order some pizza': ["pizza", "joke"],
                     'me a joke some': ["joke"],
                     'tell me a joke some': ["joke"],
                     'tell {person}': ["greet_person"]},
                    entities={'tell {person}': {"person": 'me a joke order some pizza'}})
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': ["hello", "call_person"],
                     'mom tell {person} hello': ["greet_person"]},
                    entities={'mom tell {person} hello': {"person": "her"}})
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': ["lights_on", "door_close"],
                     'close door': ["door_close"],
                     'turn on lights': ["lights_on"]})
