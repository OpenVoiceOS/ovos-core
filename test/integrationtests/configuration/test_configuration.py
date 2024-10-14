import json
from os.path import dirname, isfile
from typing import OrderedDict
from unittest import TestCase
from unittest.mock import MagicMock, patch

from ovos_config import LocalConf, RemoteConf


# TODO - move to ovos-config
class TestConfiguration(TestCase):

    @patch('ovos_backend_client.config.RemoteConfigManager')
    @patch('ovos_backend_client.pairing.is_paired')
    def test_remote(self, is_paired, config_manager):
        remote_conf = {'TestConfig': True, 'uuid': 1234,
                       'location': {'city': {'name': 'Stockholm'}}}
        is_paired.return_value = True

        mock_api = MagicMock()
        mock_api.config = remote_conf
        config_manager.return_value = mock_api

        rc = RemoteConf()
        rc.reload()
        mock_api.download.assert_called_once()
        is_paired.assert_called_once()

        self.assertTrue(rc['TestConfig'])
        self.assertEqual(rc['location']['city']['name'], 'Stockholm')

    @patch('json.dump')
    @patch('ovos_config.models.exists')
    @patch('ovos_config.models.isfile')
    @patch('ovos_config.models.load_commented_json')
    def test_local(self, mock_json_loader, mock_isfile, mock_exists,
                   mock_json_dump):
        local_conf = {'answer': 42, 'falling_objects': ['flower pot', 'whale']}
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_json_loader.return_value = local_conf
        lc = LocalConf('test')
        self.assertEqual(lc, local_conf)

        # Test merge method
        merge_conf = {'falling_objects': None, 'has_towel': True}
        lc.merge(merge_conf)
        self.assertEqual(lc['falling_objects'], None)
        self.assertEqual(lc['has_towel'], True)

        # test store
        lc.store('test_conf.json')
        self.assertEqual(mock_json_dump.call_args[0][0], lc)
        # exists but is not file
        mock_isfile.return_value = False
        lc = LocalConf('test')
        self.assertEqual(lc, {})

        # does not exist
        mock_exists.return_value = False
        lc = LocalConf('test')
        self.assertEqual(lc, {})

    def test_file_formats(self):
        yml_cnf = LocalConf(f"{dirname(__file__)}/mycroft.yml")
        json_config = LocalConf(f"{dirname(__file__)}/mycroft.json")
        self.assertEqual(json_config, yml_cnf)

        # test export json config as yaml
        json_config.store("/tmp/not_mycroft.yml")
        self.assertTrue(isfile("/tmp/not_mycroft.yml"))
        test_conf = LocalConf("/tmp/not_mycroft.yml")
        self.assertEqual(test_conf, yml_cnf)
        self.assertEqual(test_conf, json_config)

        # test export yaml config as json
        yml_cnf.store("/tmp/not_mycroft.json")
        self.assertTrue(isfile("/tmp/not_mycroft.json"))
        test_conf = LocalConf("/tmp/not_mycroft.json")
        self.assertEqual(test_conf, yml_cnf)
        self.assertEqual(test_conf, json_config)

    def test_yaml_config_load(self):
        yml_cnf = LocalConf(f"{dirname(__file__)}/mycroft.yml")
        for d in (yml_cnf, yml_cnf["hotwords"],
                  yml_cnf["hotwords"]["hey mycroft"],
                  yml_cnf["hotwords"]["wake up"]):
            self.assertIsInstance(d, dict)
            self.assertNotIsInstance(d, OrderedDict)
            self.assertEqual(json.loads(json.dumps(d)), d)
