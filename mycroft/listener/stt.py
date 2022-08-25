from ovos_config.config import Configuration
from mycroft.util.log import LOG

from ovos_plugin_manager.stt import OVOSSTTFactory, load_stt_plugin


class STTFactory(OVOSSTTFactory):
    @staticmethod
    def create(config=None):
        config = config or Configuration().get("stt", {})
        module = config.get("module", "ovos-stt-plugin-selene")
        LOG.info(f"Creating STT engine: {module}")
        return OVOSSTTFactory.create(config)
