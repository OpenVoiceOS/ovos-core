import json
from typing import OrderedDict, MutableMapping
from unittest.mock import MagicMock, patch
from unittest import TestCase, skip
import mycroft.configuration
from os.path import dirname, isfile
from mycroft.configuration import LocalConf


class TestConfiguration(TestCase):
    def test_get(self):
        d1 = {'a': 1, 'b': {'c': 1, 'd': 2}}
        d2 = {'b': {'d': 'changed'}}
        d = mycroft.configuration.Configuration.get([d1, d2])
        self.assertEqual(d['a'], d1['a'])
        self.assertEqual(d['b']['d'], d2['b']['d'])
        self.assertEqual(d['b']['c'], d1['b']['c'])

    @patch('mycroft.api.DeviceApi')
    @skip("requires backend to be enabled, TODO refactor test!")
    def test_remote(self, mock_api):
        remote_conf = {'TestConfig': True, 'uuid': 1234}
        remote_location = {'city': {'name': 'Stockholm'}}
        dev_api = MagicMock()
        dev_api.get_settings.return_value = remote_conf
        dev_api.get_location.return_value = remote_location
        mock_api.return_value = dev_api

        rc = mycroft.configuration.RemoteConf()
        self.assertTrue(rc['test_config'])
        self.assertEqual(rc['location']['city']['name'], 'Stockholm')

    @patch('json.dump')
    @patch('mycroft.configuration.config.exists')
    @patch('mycroft.configuration.config.isfile')
    @patch('mycroft.configuration.config.load_commented_json')
    def test_local(self, mock_json_loader, mock_isfile, mock_exists,
                   mock_json_dump):
        local_conf = {'answer': 42, 'falling_objects': ['flower pot', 'whale']}
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_json_loader.return_value = local_conf
        lc = mycroft.configuration.LocalConf('test')
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
        lc = mycroft.configuration.LocalConf('test')
        self.assertEqual(lc, {})

        # does not exist
        mock_exists.return_value = False
        lc = mycroft.configuration.LocalConf('test')
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

    def tearDown(self):
        mycroft.configuration.Configuration.load_config_stack([{}], True)
