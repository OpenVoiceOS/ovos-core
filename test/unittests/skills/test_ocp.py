import os.path
import unittest
from unittest.mock import patch, Mock

from ovos_classifiers.skovos.features import ClassifierProbaVectorizer
from sklearn.pipeline import FeatureUnion
import ocp_pipeline.opm
from ovos_bus_client.message import Message
from ovos_utils.ocp import MediaType
from ovos_core.intent_services.ocp_service import OCPFeaturizer, OCPPipelineMatcher
from ovos_utils.log import LOG


class TestOCPFeaturizer(unittest.TestCase):

    def setUp(self):
        self.featurizer = OCPFeaturizer()

    @patch('os.path.isfile', return_value=True)
    @patch('ovos_classifiers.skovos.features.KeywordFeaturesVectorizer.load_entities')
    @patch.object(LOG, 'info')
    def test_load_csv_with_existing_file(self, mock_log_info, mock_load_entities, mock_isfile):
        csv_path = "existing_file.csv"
        self.featurizer.load_csv([csv_path])
        mock_isfile.assert_called_with(csv_path)
        mock_load_entities.assert_called_with(csv_path)
        mock_log_info.assert_called_with(f"Loaded OCP keywords: {csv_path}")

    @patch.object(LOG, 'error')
    def test_load_csv_with_nonexistent_file(self, mock_log_error):
        csv_path = "nonexistent_file.csv"
        self.featurizer.load_csv([csv_path])
        mock_log_error.assert_called_with(f"Requested OCP entities file does not exist? {csv_path}")

    @patch.object(FeatureUnion, 'transform', return_value='mock_transform_result')
    def test_transform(self, mock_transform):
        self.featurizer.clf_feats = Mock(spec=ClassifierProbaVectorizer)
        result = self.featurizer.transform(["example_text"])
        mock_transform.assert_called_with(["example_text"])
        self.assertEqual(result, 'mock_transform_result')


class TestOCPPipelineNoClassifierMatcher(unittest.TestCase):

    def setUp(self):
        config = {
            "experimental_media_classifier": False,
            "experimental_binary_classifier": False,
            "entity_csvs": [
                os.path.dirname(ocp_pipeline.opm.__file__) + "/models/ocp_entities_v0.csv"
            ]}
        self.ocp = OCPPipelineMatcher(config=config)

    def test_match_high(self):
        result = self.ocp.match_high(["play metallica"], "en-us")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_intents')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_high_with_invalid_input(self):
        result = self.ocp.match_high(["put on some music"], "en-us")
        self.assertIsNone(result)

    def test_match_medium(self):
        result = self.ocp.match_medium(["put on some movie"], "en-us")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_media')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_medium_with_invalid_input(self):
        result = self.ocp.match_medium(["i wanna hear metallica"], "en-us")
        self.assertIsNone(result)

    def test_match_fallback(self):
        result = self.ocp.match_fallback(["i want music"], "en-us")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_fallback')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_fallback_with_invalid_input(self):
        result = self.ocp.match_fallback(["do the thing"], "en-us")
        self.assertIsNone(result)

    def test_predict(self):
        self.assertTrue(self.ocp.is_ocp_query("play a song", "en-us")[0])
        self.assertTrue(self.ocp.is_ocp_query("play a movie", "en-us")[0])
        self.assertTrue(self.ocp.is_ocp_query("play a podcast", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("tell me a joke", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("who are you", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("you suck", "en-us")[0])

    def test_predict_prob(self):
        noise = "hglisjerhksrtjhdgsf"
        self.assertEqual(self.ocp.classify_media(f"play {noise} music", "en-us")[0], MediaType.MUSIC)
        self.assertIsInstance(self.ocp.classify_media(f"play music {noise}", "en-us")[1], float)
        self.assertEqual(self.ocp.classify_media(f"play {noise} movie soundtrack", "en-us")[0], MediaType.MUSIC)
        self.assertEqual(self.ocp.classify_media(f"play movie {noise}", "en-us")[0], MediaType.MOVIE)
        self.assertEqual(self.ocp.classify_media(f"play silent {noise} movie", "en-us")[0], MediaType.SILENT_MOVIE)
        self.assertEqual(self.ocp.classify_media(f"play {noise} black and white movie", "en-us")[0],
                         MediaType.BLACK_WHITE_MOVIE)
        self.assertEqual(self.ocp.classify_media(f"play short {noise} film", "en-us")[0], MediaType.SHORT_FILM)
        self.assertEqual(self.ocp.classify_media(f"play cartoons {noise}", "en-us")[0], MediaType.CARTOON)
        self.assertEqual(self.ocp.classify_media(f"play {noise} episode", "en-us")[0], MediaType.VIDEO_EPISODES)
        self.assertEqual(self.ocp.classify_media(f"play {noise} podcast", "en-us")[0], MediaType.PODCAST)
        self.assertEqual(self.ocp.classify_media(f"play {noise} book", "en-us")[0], MediaType.AUDIOBOOK)
        self.assertEqual(self.ocp.classify_media(f"play radio {noise} FM", "en-us")[0], MediaType.RADIO)
        self.assertEqual(self.ocp.classify_media(f"read {noise}", "en-us")[0], MediaType.AUDIOBOOK)


class TestOCPPipelineMatcher(unittest.TestCase):

    def setUp(self):
        config = {
            "experimental_media_classifier": True,
            "experimental_binary_classifier": True,
            "entity_csvs": [
                os.path.dirname(ocp_pipeline.opm.__file__) + "/models/ocp_entities_v0.csv"
            ]}
        self.ocp = OCPPipelineMatcher(config=config)

    def test_match_high(self):
        result = self.ocp.match_high(["play metallica"], "en-us")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_intents')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_high_with_invalid_input(self):
        result = self.ocp.match_high(["put on some metallica"], "en-us")
        self.assertIsNone(result)

    def test_match_medium(self):
        result = self.ocp.match_medium(["put on some metallica"], "en-us")
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_media')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_medium_with_invalid_input(self):
        result = self.ocp.match_medium(["i wanna hear metallica"], "en-us")
        self.assertIsNone(result)

    def test_match_fallback(self):
        result = self.ocp.match_fallback(["i wanna hear metallica"], "en-us")
        print(result)
        self.assertIsNotNone(result)
        self.assertEqual(result.intent_service, 'OCP_fallback')
        self.assertEqual(result.intent_type, 'ocp:play')

    def test_match_fallback_with_invalid_input(self):
        result = self.ocp.match_fallback(["do the thing"], "en-us")
        self.assertIsNone(result)

    def test_predict(self):
        self.assertTrue(self.ocp.is_ocp_query("play a song", "en-us")[0])
        self.assertTrue(self.ocp.is_ocp_query("play my morning jams", "en-us")[0])
        self.assertTrue(self.ocp.is_ocp_query("i want to watch the matrix", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("tell me a joke", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("who are you", "en-us")[0])
        self.assertFalse(self.ocp.is_ocp_query("you suck", "en-us")[0])

    def test_predict_prob(self):
        # "metallica" in csv dataset
        self.ocp.config["classifier_threshold"] = 0.2
        self.assertEqual(self.ocp.classify_media("play metallica", "en-us")[0], MediaType.MUSIC)
        self.assertIsInstance(self.ocp.classify_media("play metallica", "en-us")[1], float)
        self.ocp.config["classifier_threshold"] = 0.5
        self.assertEqual(self.ocp.classify_media("play metallica", "en-us")[0], MediaType.GENERIC)
        self.assertIsInstance(self.ocp.classify_media("play metallica", "en-us")[1], float)

    @unittest.skip("TODO - classifiers needs retraining")
    def test_predict_prob_with_unknown_entity(self):
        # "klownevilus" not in the csv dataset
        self.ocp.config["classifier_threshold"] = 0.2
        self.assertEqual(self.ocp.classify_media("play klownevilus", "en-us")[0], MediaType.MUSIC)
        self.assertIsInstance(self.ocp.classify_media("play klownevilus", "en-us")[1], float)
        self.ocp.config["classifier_threshold"] = 0.5
        self.assertEqual(self.ocp.classify_media("play klownevilus", "en-us")[0], MediaType.GENERIC)

        self.ocp.config["classifier_threshold"] = 0.1
        self.ocp.handle_skill_keyword_register(Message("", {
            "skill_id": "fake",
            "label": "movie_name",
            "media_type": MediaType.MOVIE,
            "samples": ["klownevilus"]
        }))
        # should be MOVIE not MUSIC  TODO fix me
        self.assertEqual(self.ocp.classify_media("play klownevilus", "en-us")[0], MediaType.MOVIE)


if __name__ == '__main__':
    unittest.main()
