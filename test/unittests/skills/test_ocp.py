import os.path
import unittest
from unittest.mock import patch, Mock
import ovos_core.intent_services.ocp_service
from ovos_core.intent_services.ocp_service import OCPFeaturizer, OCPPipelineMatcher
from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
from ovos_classifiers.skovos.features import ClassifierProbaVectorizer, KeywordFeaturesVectorizer
from sklearn.pipeline import FeatureUnion
from ovos_utils.log import LOG
from ovos_bus_client.message import Message
from ovos_core.intent_services.ocp_service import MediaType


class TestOCPFeaturizer(unittest.TestCase):

    def setUp(self):
        self.featurizer = OCPFeaturizer()

    @patch('os.path.isfile', return_value=True)
    @patch('ovos_core.intent_services.ocp_service.KeywordFeaturesVectorizer.load_entities')
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



class TestOCPPipelineMatcher(unittest.TestCase):

    def setUp(self):
        config = {"entity_csvs": [
            os.path.dirname(ovos_core.intent_services.ocp_service.__file__) + "/models/ocp_entities_v0.csv"
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
