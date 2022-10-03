# This submodule has been deprecated, please import from ovos_backend_client directly
from mycroft.deprecated.api import Api, UUID, GeolocationApi, STTApi, DeviceApi
from ovos_backend_client.pairing import has_been_paired, is_paired, check_remote_pairing, \
    is_backend_disabled, requires_backend
from ovos_backend_client.exceptions import BackendDown, InternetDown
