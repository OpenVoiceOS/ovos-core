from copy import copy

import requests
from requests.exceptions import HTTPError
from selene_api.api import STTApi as _STTApi, GeolocationApi as _GeoApi, BaseApi
from ovos_config.config import Configuration
from ovos_utils.log import LOG

UUID = '{MYCROFT_UUID}'


class Api(BaseApi):
    """ Generic class to wrap web APIs
    backwards compat only, please use selene_api package directly"""

    params_to_etag = {}
    etag_to_response = {}

    def __init__(self, path):
        self.path = path
        config = Configuration()
        config_server = config.get("server") or {}
        url = config_server.get("url")
        version = config_server.get("version")
        super().__init__(url, version)
        from mycroft.api import is_backend_disabled
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
        LOG.warning("mycroft.api module has been deprecated, please use selene_api directly")
        LOG.warning("use 'from selene_api.api import GeolocationApi' instead")
        super().__init__('geolocation')
        self._real_api = _GeoApi(self.url, self.version)

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
        LOG.warning("mycroft.api module has been deprecated, please use selene_api directly")
        LOG.warning("use 'from selene_api.api import STTApi' instead")
        super(STTApi, self).__init__(path)
        self._real_api = _STTApi(self.url, self.version)

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


