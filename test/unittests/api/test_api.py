# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import unittest
from copy import copy
import selene_api
from unittest.mock import MagicMock, patch

import mycroft.api
import mycroft.configuration
from mycroft.configuration import Configuration
from test.util import base_config

# TODO move test to selene_api repo

CONFIG = base_config()
CONFIG.merge(
    {
        'data_dir': '/opt/mycroft',
        'server': {
            'url': 'https://api-test.mycroft.ai',
            'version': 'v1',
            'update': True,
            'metrics': False
        }
    }
)

selene_api.api.requests.post = MagicMock()


def create_identity(uuid, expired=False):
    mock_identity = MagicMock()
    mock_identity.is_expired.return_value = expired
    mock_identity.uuid = uuid
    return mock_identity


def create_response(status, json=None, url='', data=''):
    json = json or {}
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json
    response.url = url
    return response


@patch.dict(Configuration._Configuration__patch, CONFIG)
class TestApi(unittest.TestCase):
    @patch('selene_api.identity.IdentityManager.get')
    def test_init(self, mock_identity_get):
        mock_identity_get.return_value = create_identity('1234')
        a = mycroft.api.Api('test-path')
        self.assertEqual(a.url, 'https://api-test.mycroft.ai')
        self.assertEqual(a.version, 'v1')
        self.assertEqual(a.identity.uuid, '1234')

    @unittest.skip("requires backend to be enabled, TODO refactor test!")
    @patch('selene_api.identity.IdentityManager')
    @patch('selene_api.api.requests.request')
    def test_send(self, mock_request, mock_identity_manager):
        # Setup an OK response
        mock_response_ok = create_response(200, {})
        mock_response_301 = create_response(301, {})
        mock_response_401 = create_response(401, {}, 'auth/token')
        mock_response_refresh = create_response(401, {}, '')

        mock_request.return_value = mock_response_ok
        a = mycroft.api.Api('test-path')
        req = {'path': 'something', 'headers': {}}

        # Check successful
        self.assertEqual(a.send(req), mock_response_ok.json())

        # check that a 300+ status code generates Exception
        mock_request.return_value = mock_response_301
        with self.assertRaises(selene_api.exceptions.HTTPError):
            a.send(req)

        # Check 401
        mock_request.return_value = mock_response_401
        req = {'path': '', 'headers': {}}
        with self.assertRaises(selene_api.exceptions.HTTPError):
            a.send(req)

        # Check refresh token
        a.old_params = copy(req)
        mock_request.side_effect = [mock_response_refresh, mock_response_ok,
                                    mock_response_ok]
        req = {'path': 'something', 'headers': {}}
        a.send(req)
        self.assertTrue(selene_api.identity.IdentityManager.save.called)


#@unittest.skip("requires backend to be enabled, TODO refactor test!")
@patch.dict(Configuration._Configuration__patch, CONFIG)
class TestDeviceApi(unittest.TestCase):

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.request')
    def test_init(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity_get.return_value = create_identity('1234')

        device = selene_api.api.DeviceApi()
        self.assertEqual(device.identity.uuid, '1234')
        self.assertTrue(device.url.endswith("/device"))

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.post')
    def test_device_activate(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity_get.return_value = create_identity('1234')
        # Test activate
        device = selene_api.api.DeviceApi()
        device.activate('state', 'token')
        json = mock_request.call_args[1]['json']
        self.assertEqual(json['state'], 'state')
        self.assertEqual(json['token'], 'token')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity_get.return_value = create_identity('1234')
        # Test get
        device = selene_api.api.DeviceApi()
        device.get()
        url = mock_request.call_args[0][0]
        self.assertEqual(url, 'https://api-test.mycroft.ai/v1/device/1234')

    @patch('selene_api.identity.IdentityManager.update')
    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get_code(self, mock_request, mock_identity_get,
                             mock_identit_update):
        mock_request.return_value = create_response(200, '123ABC')
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        ret = device.get_code('state')
        self.assertEqual(ret, '123ABC')
        url = mock_request.call_args[0][0]
        params = mock_request.call_args[1]
        self.assertEqual(url, 'https://api-test.mycroft.ai/v1/device/code')
        self.assertEqual(params["params"], {"state": "state"})

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get_settings(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.get_settings()
        url = mock_request.call_args[0][0]
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/setting')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.post')
    def test_device_report_metric(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.report_metric('mymetric', {'data': 'mydata'})
        url = mock_request.call_args[0][0]
        params = mock_request.call_args[1]

        content_type = params['headers']['Content-Type']
        correct_json = {'data': 'mydata'}
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(params['json'], correct_json)
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/metric/mymetric')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.put')
    def test_device_send_email(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.send_email('title', 'body', 'sender')
        url = mock_request.call_args[0][0]
        params = mock_request.call_args[1]

        content_type = params['headers']['Content-Type']
        correct_json = {'body': 'body', 'sender': 'sender', 'title': 'title'}
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(params['json'], correct_json)
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/message')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get_oauth_token(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.get_oauth_token(1)
        url = mock_request.call_args[0][0]

        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/token/1')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get_location(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.get_location()
        url = mock_request.call_args[0][0]
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/location')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_device_get_subscription(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.get_subscription()
        url = mock_request.call_args[0][0]
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/subscription')

        mock_request.return_value = create_response(200, {'@type': 'free'})
        self.assertFalse(device.is_subscriber)

        mock_request.return_value = create_response(200, {'@type': 'monthly'})
        self.assertTrue(device.is_subscriber)

        mock_request.return_value = create_response(200, {'@type': 'yearly'})
        self.assertTrue(device.is_subscriber)

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.put')
    def test_device_upload_skills_data(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.upload_skills_data({})
        url = mock_request.call_args[0][0]
        data = mock_request.call_args[1]['json']

        # Check that the correct url is called
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/skillJson')

        # Check that the correct data is sent as json
        self.assertTrue('blacklist' in data)
        self.assertTrue('skills' in data)

        with self.assertRaises(ValueError):
            device.upload_skills_data('This isn\'t right at all')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_stt(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        stt = selene_api.api.STTApi('stt')
        self.assertTrue(stt.url.endswith('stt'))

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.post')
    def test_stt_stt(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        stt = selene_api.api.STTApi('https://api-test.mycroft.ai')
        stt.stt('La la la', 'en-US', 1)
        url = mock_request.call_args[0][0]
        self.assertEqual(url, 'https://api-test.mycroft.ai/v1/stt')
        data = mock_request.call_args[1].get('data')
        self.assertEqual(data, 'La la la')
        params = mock_request.call_args[1].get('params')
        self.assertEqual(params['lang'], 'en-US')

    @patch('selene_api.identity.IdentityManager.load')
    def test_has_been_paired(self, mock_identity_load):
        # reset pairing cache
        mock_identity = MagicMock()
        mock_identity_load.return_value = mock_identity
        # Test None
        mock_identity.uuid = None
        self.assertFalse(selene_api.pairing.has_been_paired())
        # Test empty string
        mock_identity.uuid = ""
        self.assertFalse(selene_api.pairing.has_been_paired())
        # Test actual id number
        mock_identity.uuid = "1234"
        self.assertTrue(selene_api.pairing.has_been_paired())


@patch.dict(Configuration._Configuration__patch, CONFIG)
class TestSettingsMeta(unittest.TestCase):

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.put')
    def test_upload_meta(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()

        settings_meta = {
            'name': 'TestMeta',
            "skill_gid": 'test_skill|19.02',
            'skillMetadata': {
                'sections': [
                    {
                        'name': 'Settings',
                        'fields': [
                            {
                                'name': 'Set me',
                                'type': 'number',
                                'value': 4
                            }
                        ]
                    }
                ]
            }
        }
        device.upload_skill_metadata(settings_meta)
        url = mock_request.call_args[0][0]
        params = mock_request.call_args[1]

        content_type = params['headers']['Content-Type']
        self.assertEqual(content_type, 'application/json')
        self.assertEqual(params['json'], settings_meta)
        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/settingsMeta')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_get_skill_settings(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200, {})
        mock_identity_get.return_value = create_identity('1234')
        device = selene_api.api.DeviceApi()
        device.get_skill_settings()
        url = mock_request.call_args[0][0]
        params = mock_request.call_args[1]

        self.assertEqual(
            url, 'https://api-test.mycroft.ai/v1/device/1234/skill/settings')


@patch.dict(Configuration._Configuration__patch, CONFIG)
@patch('selene_api.pairing._paired_cache', False)
class TestIsPaired(unittest.TestCase):
    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_is_paired_true(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity = MagicMock()
        mock_identity.is_expired.return_value = False
        mock_identity.uuid = '1234'
        mock_identity_get.return_value = mock_identity
        num_calls = mock_identity_get.num_calls
        # reset paired cache

        self.assertTrue(selene_api.pairing.is_paired())

        self.assertEqual(num_calls, mock_identity_get.num_calls)
        url = mock_request.call_args[0][0]
        self.assertEqual(url, 'https://api-test.mycroft.ai/v1/device/1234')

    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_is_paired_false_local(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(200)
        mock_identity = MagicMock()
        mock_identity.is_expired.return_value = False
        mock_identity.uuid = ''
        mock_identity_get.return_value = mock_identity

        self.assertFalse(selene_api.pairing.is_paired())
        mock_identity.uuid = None
        self.assertFalse(selene_api.pairing.is_paired())

    @unittest.skip("TODO - refactor/fix test")
    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_is_paired_false_remote(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(401)
        mock_identity = MagicMock()
        mock_identity.is_expired.return_value = False
        mock_identity.uuid = '1234'
        mock_identity_get.return_value = mock_identity
        selene_api.pairing._paired_cache = False
        self.assertFalse(selene_api.pairing.is_paired())

    @unittest.skip("TODO - refactor/fix test")
    @patch('selene_api.identity.IdentityManager.get')
    @patch('selene_api.api.requests.get')
    def test_is_paired_error_remote(self, mock_request, mock_identity_get):
        mock_request.return_value = create_response(500)
        mock_identity = MagicMock()
        mock_identity.is_expired.return_value = False
        mock_identity.uuid = '1234'
        mock_identity_get.return_value = mock_identity

        self.assertFalse(selene_api.pairing.is_paired())

        with self.assertRaises(selene_api.exceptions.BackendDown):
            selene_api.pairing.is_paired(ignore_errors=False)
