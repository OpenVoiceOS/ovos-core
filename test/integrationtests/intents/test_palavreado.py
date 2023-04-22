import unittest

from lingua_franca.internal import load_language

from neon_intent_plugin_palavreado import PalavreadoExtractor


class TestPalavreado(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        load_language("en-us")  # setup LF normalizer

        intents = PalavreadoExtractor()

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

        intents.register_entity("weather", weather)
        intents.register_entity("hello", hello)
        intents.register_entity("name", name)
        intents.register_entity("joke", joke)
        intents.register_entity("door", door)
        intents.register_entity("lights", light)
        intents.register_entity("on", on)
        intents.register_entity("off", off)
        intents.register_entity("play", play)
        intents.register_entity("music", music)
        intents.register_entity("say", say)

        intents.register_intent("weather", ["weather"], ["say"])
        intents.register_intent("hello", ["hello"])
        intents.register_intent("name", ["name"])
        intents.register_intent("joke", ["joke"], ["say"])
        intents.register_intent("lights_on", ["lights", "on"])
        intents.register_intent("lights_off", ["lights", "off"])
        intents.register_intent("door_open", ["door", "on"])
        intents.register_intent("door_close", ["door", "off"])
        intents.register_intent("play_music", ["play", "music"])

        self.engine = intents

    def test_single_intent(self):
        # get intent from utterance mycroft style
        # 1 utterance -> 1 intent

        def test_intent(sent, intent_type, remainder):
            res = self.engine.calc_intent(sent)
            self.assertEqual(res["intent_engine"], "palavreado")
            self.assertEqual(res["intent_type"], intent_type)
            self.assertEqual(res["utterance_remainder"], remainder)

        # multiple known intents in utterance
        # TODO Remainder is imperfect due to normalization, but let it pass for now
        test_intent("tell me a joke and say hello", "joke", 'me a and hello')
        test_intent("tell me a joke and the weather", "weather", 'me a joke and the')
        test_intent("close the door turn off the lights", "lights_off", 'the door turn the')
        test_intent("close the pod bay doors play some music", "door_close", 'the pod bay play some music')

        # known + unknown intents in utterance
        test_intent("tell me a joke order some pizza", "joke", 'me a order some pizza')

        # unknown intents
        test_intent("Call mom tell her hello", "hello", 'Call mom tell her')  # "hello" intent is closest match
        test_intent("nice work! get me a beer", "unknown", 'nice work! get me a beer')  # no intent at all

        # conflicting/badly modeled intents
        test_intent("turn off the lights, open the door", "lights_on",
                    'turn off the , the door')  # "open" and "off" conflict
        test_intent("turn on the lights close the door", "lights_off",
                    'turn on the the door')  # "on" and "close" conflict

    def test_main_secondary_intent(self):
        # get intent -> get intent from utt remainder
        # 1 utterance -> 2 intents

        def test_intent(sent, intents):
            res = self.engine.intent_remainder(sent)
            if len(res) == 1:
                first = res[0]
                second = {"intent_type": "unknown", "intent_engine": "palavreado"}
            else:
                first, second = res[0], res[1]

            self.assertEqual(first["intent_engine"], "palavreado")
            self.assertEqual(second["intent_engine"], "palavreado")

            self.assertEqual({first["intent_type"], second["intent_type"]}, set(intents))

        # multiple known intents in utterance
        test_intent("tell me a joke and say hello", {"joke", 'hello'})
        test_intent("tell me a joke and the weather", {"weather", 'joke'})
        test_intent("close the pod bay doors play some music", {'play_music', 'door_close'})

        # known + unknown intents in utterance
        test_intent("tell me a joke order some pizza", {'joke', 'unknown'})
        test_intent("Call mom tell her hello", {'hello', 'weather'})  # weather is 0.07% conf due to "tell" keyword

        # unknown intents
        test_intent("nice work! get me a beer", {'unknown', 'unknown'})  # no intent at all

        # conflicting/badly modeled intents
        # (keyword order is not taken into account)
        test_intent("turn off the lights, open the door", {'lights_on', 'door_close'})  # "open" and "off" conflict
        test_intent("turn on the lights close the door", {'lights_off', 'door_open'})  # "on" and "close" conflict

        # fail due to main intent capturing multiple words
        # {'lights': ['lights'], 'off': ['close', 'off']} -> utterance remainder == 'the door turn the'
        test_intent("close the door turn off the lights", {'door_open', 'lights_off'})

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
                    {'get me a beer': [], 'nice work': []})

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
        test_intent("turn on the lights close the door",
                    {'turn on the lights close the door': ["lights_off"]})  # "on" and "close" conflict

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
                self.assertEqual(res["intent_engine"], "palavreado")
                self.assertIn(utt, expected)
                self.assertEqual(res["intent_type"], expected[utt])

        # multiple known intents in utterance
        test_intent("tell me a joke and say hello",
                    {'say hello': "hello", 'tell me a joke': "joke"})
        test_intent("tell me a joke and the weather",
                    {'the weather': 'weather', 'tell me a joke': "joke"})

        # conflicting/badly modeled intents -> no conflict due to good segmentation
        test_intent("turn off the lights, open the door",
                    {'turn off the lights': "lights_off", 'open the door': "door_open"})

        # failed segmentation (no markers to split)
        test_intent("close the door turn off the lights",
                    {'close the door turn off the lights': "lights_off"})
        test_intent("close the pod bay doors play some music",
                    {'the pod bay play some music': "play_music",
                     'close the pod bay doors play some music': "door_close"})

        # known + unknown intents in utterance + failed segmentation
        test_intent("tell me a joke order some pizza",
                    {'tell me a joke order some pizza': "joke"})
        test_intent("Call mom tell her hello",
                    {'Call mom tell her hello': "hello"})

        # conflicting/badly modeled intents -> conflict due to failed segmentation
        test_intent("turn on the lights close the door",
                    {'turn on the the door': "door_open",
                     'turn on the lights close the door': "lights_off"})  # "on" and "close" conflict
