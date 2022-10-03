from copy import copy

import requests
from requests.exceptions import HTTPError
from mycroft.version import VersionManager, OVOS_VERSION_STR
from ovos_backend_client.api import STTApi as _STTApi, GeolocationApi as _GeoApi, BaseApi, DeviceApi as _DeviceApi
from ovos_config.config import Configuration
from ovos_utils.log import LOG
from ovos_backend_client.pairing import has_been_paired, is_paired, check_remote_pairing, \
    is_backend_disabled, requires_backend


UUID = '{MYCROFT_UUID}'


class Api(BaseApi):
    """ Generic class to wrap web APIs
    backwards compat only, please use ovos_backend_client package directly"""

    params_to_etag = {}
    etag_to_response = {}

    def __init__(self, path):
        self.path = path
        config = Configuration()
        config_server = config.get("server") or {}
        url = config_server.get("url")
        version = config_server.get("version")
        super().__init__(url, version)
        self.disabled = is_backend_disabled()

    @property
    def version(self):
        return self.backend_version

    def request(self, params):
        self.check_token()
        if 'path' in params:
            params['path'] = params['path'].replace(UUID, self.identity.uuid)
        self.build_path(params)
        self.old_params = copy(params)
        return self.send(params) or {}

    def get_data(self, response):
        try:
            return response.json()
        except Exception:
            return response.text

    def build_headers(self, params):
        headers = params.get("headers", {})
        self.add_content_type(headers)
        self.add_authorization(headers)
        params["headers"] = headers
        return headers

    def add_content_type(self, headers):
        if not headers.__contains__("Content-Type"):
            headers["Content-Type"] = "application/json"

    def add_authorization(self, headers):
        if not headers.__contains__("Authorization"):
            headers["Authorization"] = "Bearer " + self.identity.access

    def build_data(self, params):
        return params.get("data")

    def build_json(self, params):
        json = params.get("json")
        if json and params["headers"]["Content-Type"] == "application/json":
            for k, v in json.items():
                if v == "":
                    json[k] = None
            params["json"] = json
        return json

    def build_query(self, params):
        return params.get("query")

    def build_path(self, params):
        path = params.get("path", "")
        params["path"] = self.path + path
        return params["path"]

    def build_url(self, params):
        path = params.get("path", "")
        version = params.get("version", self.version)
        return self.url + "/" + version + "/" + path

    def send(self, params, no_refresh=False):
        """ Send request to mycroft backend.
        The method handles Etags and will return a cached response value
        if nothing has changed on the remote.

        Args:
            params (dict): request parameters
            no_refresh (bool): optional parameter to disable refreshs of token

        Returns:
            Requests response object.
        """
        if self.disabled:
            return {}
        query_data = frozenset(params.get('query', {}).items())
        params_key = (params.get('path'), query_data)
        etag = self.params_to_etag.get(params_key)

        method = params.get("method", "GET")
        headers = self.build_headers(params)
        data = self.build_data(params)
        json_body = self.build_json(params)
        query = self.build_query(params)
        url = self.build_url(params)

        # For an introduction to the Etag feature check out:
        # https://en.wikipedia.org/wiki/HTTP_ETag
        if etag:
            headers['If-None-Match'] = etag

        response = requests.request(
            method, url, headers=headers, params=query,
            data=data, json=json_body, timeout=(3.05, 15)
        )
        if response.status_code == 304:
            # Etag matched, use response previously cached
            response = self.etag_to_response[etag]
        elif 'ETag' in response.headers:
            etag = response.headers['ETag'].strip('"')
            # Cache response for future lookup when we receive a 304
            self.params_to_etag[params_key] = etag
            self.etag_to_response[etag] = response

        return self.get_response(response, no_refresh)

    def get_response(self, response, no_refresh=False):
        """ Parse response and extract data from response.

        Will try to refresh the access token if it's expired.

        Args:
            response (requests Response object): Response to parse
            no_refresh (bool): Disable refreshing of the token

        Returns:
            data fetched from server
        """
        if self.disabled:
            return {}
        data = self.get_data(response)

        if 200 <= response.status_code < 300:
            return data
        elif all([not no_refresh,
                  response.status_code == 401,
                  not response.url.endswith("auth/token"),
                  self.identity.is_expired()]):
            self.refresh_token()
            return self.send(self.old_params, no_refresh=True)
        raise HTTPError(data, response=response)


class GeolocationApi(Api):
    """Web API wrapper for performing geolocation lookups."""

    def __init__(self):
        LOG.warning("mycroft.api module has been deprecated, please use ovos_backend_client directly")
        LOG.warning("use 'from ovos_backend_client.api import GeolocationApi' instead")
        super().__init__('geolocation')

    @property
    def _real_api(self):
        """ this is a property to reflect live updates to backend url """
        return _GeoApi()

    def get_geolocation(self, location):
        """Call the geolocation endpoint.

        Args:
            location (str): the location to lookup (e.g. Kansas City Missouri)

        Returns:
            str: JSON structure with lookup results
        """
        return self._real_api.get_geolocation(location)


class STTApi(Api):
    """ Web API wrapper for performing Speech to Text (STT) """

    def __init__(self, path):
        LOG.warning("mycroft.api module has been deprecated, please use ovos_backend_client directly")
        LOG.warning("use 'from ovos_backend_client.api import STTApi' instead")
        super(STTApi, self).__init__(path)

    @property
    def _real_api(self):
        """ this is a property to reflect live updates to backend url """
        return _STTApi()

    def stt(self, audio, language, limit):
        """ Web API wrapper for performing Speech to Text (STT)

        Args:
            audio (bytes): The recorded audio, as in a FLAC file
            language (str): A BCP-47 language code, e.g. "en-US"
            limit (int): Maximum minutes to transcribe(?)

        Returns:
            str: JSON structure with transcription results
        """

        return self._real_api.stt(audio, language, limit)


class DeviceApi(Api):
    """ Web API wrapper for obtaining device-level information
    selene_api is not used directly to account for disabled_backend setting"""

    def __init__(self):
        LOG.warning("mycroft.api module has been deprecated, please use ovos_backend_client directly")
        LOG.warning("use 'from ovos_backend_client.api import DeviceApi' instead")
        super(DeviceApi, self).__init__("device")

    @property
    def _real_api(self):
        """ this is a property to reflect live updates to backend url """
        return _DeviceApi()

    def get_code(self, state):
        return self._real_api.get_code(state)

    def activate(self, state, token):
        version = VersionManager.get()
        platform = "ovos-core"
        platform_build = OVOS_VERSION_STR
        return self._real_api.activate(state, token, version.get("coreVersion"),
                                       platform, platform_build, version.get("enclosureVersion"))

    def update_version(self):
        version = VersionManager.get()
        platform = "ovos-core"
        platform_build = OVOS_VERSION_STR
        return self._real_api.update_version(version.get("coreVersion"),
                                             platform, platform_build,
                                             version.get("enclosureVersion"))

    def send_email(self, title, body, sender):
        return self._real_api.send_email(title, body, sender)

    def report_metric(self, name, data):
        return self._real_api.report_metric(name, data)

    def get(self):
        """ Retrieve all device information from the web backend """
        return self._real_api.get()

    def get_settings(self):
        """ Retrieve device settings information from the web backend

        Returns:
            str: JSON string with user configuration information.
        """
        return self._real_api.get_settings()

    def get_location(self):
        """ Retrieve device location information from the web backend

        Returns:
            str: JSON string with user location.
        """
        return self._real_api.get_location()

    def get_subscription(self):
        """
            Get information about type of subscrition this unit is connected
            to.

            Returns: dictionary with subscription information
        """
        return self._real_api.get_subscription()

    @property
    def is_subscriber(self):
        """
            status of subscription. True if device is connected to a paying
            subscriber.
        """
        return self._real_api.is_subscriber

    def get_subscriber_voice_url(self, voice=None):
        return self._real_api.get_subscriber_voice_url(voice)

    def get_oauth_token(self, dev_cred):
        """
            Get Oauth token for dev_credential dev_cred.

            Argument:
                dev_cred:   development credentials identifier

            Returns:
                json string containing token and additional information
        """
        return self._real_api.get_oauth_token(dev_cred)

    def get_skill_settings(self):
        """Get the remote skill settings for all skills on this device."""
        return self._real_api.get_skill_settings()

    def upload_skill_metadata(self, settings_meta):
        """Upload skill metadata.

        Args:
            settings_meta (dict): skill info and settings in JSON format
        """
        return self._real_api.upload_skill_metadata(settings_meta)

    def upload_skills_data(self, data):
        """ Upload skills.json file. This file contains a manifest of installed
        and failed installations for use with the Marketplace.

        Args:
             data: dictionary with skills data from msm
        """
        return self._real_api.upload_skills_data(data)
