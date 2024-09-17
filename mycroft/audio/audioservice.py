# backwards compat imports
from ovos_audio.audio import AudioService
from ovos_plugin_manager.audio import setup_audio_service as setup_service, load_audio_service_plugins as load_plugins
from ovos_plugin_manager.templates.audio import RemoteAudioBackend

# deprecated, but can not be deleted for backwards compat imports
from mycroft.deprecated.audio import load_internal_services, load_services, create_service_spec, get_services

MINUTES = 60  # Seconds in a minute

