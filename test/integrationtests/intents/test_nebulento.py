import unittest

from lingua_franca.internal import load_language

from neon_intent_plugin_nebulento import NebulentoExtractor


class TestNebulentoExtractor(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        load_language("en-us")  # setup LF normalizer

        intents = NebulentoExtractor()

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

        persons = ["Peter", "Ken", "Maria"]
        intents.register_entity("person", persons)

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

        def test_intent(sent, intent, best_match, entities=None, min_conf=0.5):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "nebulento")
            self.assertEqual(res["best_match"], best_match)
            self.assertIn(res["intent_type"], intent)
            self.assertLess(min_conf, res["conf"])
            if entities:
                self.assertEqual(res["entities"], entities)

        def test_intent_fail(sent, min_conf=0.5):
            res = self.engine.calc_intent(sent, min_conf=min_conf)
            self.assertEqual(res["intent_engine"], "nebulento")
            self.assertIn(res["intent_type"], "unknown")
            self.assertIn(res["utterance_remainder"], sent)

        # expected matches
        test_intent("close the door turn off the lights", 'lights_off',
                    best_match='turn off the lights', min_conf=0.7)
        test_intent("close the pod bay doors play some music", 'door_close',
                    best_match='close the doors')
        test_intent("turn off the lights, open the door", 'lights_off',
                    best_match='turn off the lights', min_conf=0.7)
        test_intent("turn on the lights close the door", 'lights_on',
                    best_match='turn on the lights', min_conf=0.7)
        test_intent("tell me a joke and the weather", "joke",
                    best_match='tell me a joke', min_conf=0.6)
        test_intent("tell me a joke order some pizza", "joke",
                    best_match='tell me a joke', min_conf=0.6)
        test_intent("tell me a joke and say hello", "joke",
                    best_match='tell me a joke')
        test_intent(
            "tell me a joke and order some pizza and turn on the lights and close the door and play some songs",
            'lights_on',
            best_match='turn on the lights', min_conf=0.3)

        # TODO capitalization gets messed up in extracted entity
        test_intent("Call Ken tell him hello", 'greet_person',
                    best_match='tell {person} hello', entities={'person': 'ken'})
        test_intent("Call Bob tell him hello", 'greet_person',
                    best_match='tell {person} hello', entities={})  # failed entity

        # failed intents
        test_intent_fail(
            "tell me a joke and order some pizza and turn on the lights and close the door and play some songs",
            min_conf=0.5)

        # unknown intents
        test_intent_fail("nice work! get me a beer")

    def test_main_secondary_intent(self):
        # get intent -> get intent from utt remainder
        # 1 utterance -> 2 intents

        def test_intent(sent, intent, intent2="unknown",
                        best_match="", best_match2="",
                        consumed="", consumed2="",
                        remainder="", remainder2="",
                        entities=None, entities2=None):
            res = self.engine.intent_remainder(sent)
            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "nebulento", "best_match": ""}
            else:
                first, second = res[0], res[1]

            self.assertEqual(first["intent_engine"], "nebulento")
            self.assertEqual(second["intent_engine"], "nebulento")
            self.assertEqual(first["intent_type"], intent)
            self.assertEqual(second["intent_type"], intent2)
            self.assertEqual(first["utterance_consumed"], consumed)
            self.assertEqual(second["utterance_consumed"], consumed2)
            self.assertEqual(first["utterance_remainder"], remainder)
            self.assertEqual(second["utterance_remainder"], remainder2)
            self.assertEqual(first["best_match"], best_match)
            self.assertEqual(second.get("best_match", ""), best_match2)
            if entities:
                self.assertEqual(first["entities"], entities)
            if entities2:
                self.assertEqual(second["entities"], entities2)

        def test_intent_fail(sent):
            res = self.engine.intent_remainder(sent)[0]
            print(res)
            self.assertEqual(res["intent_engine"], "nebulento")
            self.assertEqual(res["intent_type"], "unknown")

        test_intent("close the door turn off the lights",
                    "lights_off", "door_close",
                    consumed='the turn off the lights', consumed2='close door',
                    remainder='close door', remainder2="",
                    best_match="turn off the lights", best_match2="close door")
        test_intent("turn off the lights, open the door",
                    "lights_off", "door_open",
                    consumed='turn off the lights the', consumed2='open door',
                    remainder='open door', remainder2="",
                    best_match="turn off the lights", best_match2="open door")
        test_intent("turn on the lights close the door", "lights_on", "door_close",
                    consumed='turn on the lights the', consumed2='close door',
                    remainder='close door', remainder2="",
                    best_match="turn on the lights", best_match2="close door")
        test_intent("tell me a joke order some pizza", "joke", "pizza",
                    consumed='tell me a joke', consumed2='order pizza',
                    remainder='order some pizza', remainder2="some",
                    best_match='tell me a joke', best_match2='order pizza')
        test_intent("tell me a joke and the weather", "joke", "weather",
                    consumed='tell me a joke', consumed2='weather',
                    remainder='and the weather', remainder2="and the",
                    best_match='tell me a joke', best_match2='weather')

        # partial match
        test_intent("tell me a joke and say hello", "joke", "unknown",
                    consumed='tell me a joke', consumed2='',
                    remainder='and say hello', remainder2="and say hello",
                    best_match='tell me a joke', best_match2='')
        test_intent("Call Ken tell him hello", "greet_person", "unknown",
                    consumed='tell hello ken', consumed2='',
                    remainder='call him', remainder2="call him",
                    best_match='tell {person} hello', best_match2='',
                    entities={'person': 'ken'}, entities2={})

        # failed intents
        test_intent_fail("close the pod bay doors play some music")
        test_intent_fail("Call Bob tell him hello")  # failed entity

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
                    {'get me a beer': [], 'nice work': []})

        # failed segmentation (no markers to split)
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': ["joke"]})
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': ['greet_person']})
        test_intent("close the door turn off the lights",
                    {'close the door turn off the lights': ['lights_off']})
        test_intent("close the pod bay doors play some music",
                    {'close the pod bay doors play some music': []})
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': ["lights_on"]})

    def test_segment_main_secondary_intent(self):
        # segment -> get intent -> get intent from utt remainder
        # 1 utterance -> N intents
        # segmentation can get any number of sub-utterances
        # each sub-utterance can have 2 intents

        def test_intent(sent, expected, entities=None):
            entities = entities or {}
            for res in self.engine.intents_remainder(sent):
                if res["utterance_consumed"] == "":
                    continue
                utt = res["utterance"]
                self.assertEqual(res["intent_engine"], "nebulento")
                self.assertIn(utt, expected)
                self.assertEqual(res["intent_type"], expected[utt])
                if utt in entities:
                    self.assertEqual(entities[utt], res["entities"])

        # good segmentation
        test_intent("tell me a joke and say hello",
                    {'say hello': "hello",
                     'tell me a joke': "joke"})
        test_intent("tell me a joke and the weather",
                    {'the weather': 'weather',
                     'tell me a joke': "joke"})
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': "lights_off",
                     'open the door': "door_open"})

        # failed segmentation (no markers to split)
        # use remainder onlu
        test_intent("close the door turn off the lights",
                    {'close door': "door_close",
                     "close the door turn off the lights": "lights_off"})
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': "joke",
                     'order some pizza': "pizza"})
        test_intent("close the pod bay doors play some music",
                    {'close the pod bay doors play some music': "lights_off",
                     'open the door': "door_open"})
        test_intent("call mom tell her hello",
                    {'call mom tell her hello': "greet_person"})
        test_intent("call ken tell him hello",
                    {'call ken tell him hello': "greet_person"},
                    entities={'call ken tell him hello': {"person": "ken"}})
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': "lights_on",
                     'close door': "door_close"})
