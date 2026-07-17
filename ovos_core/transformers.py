from typing import Optional

from ovos_config import Configuration
from ovos_plugin_manager.intent_transformers import find_intent_transformer_plugins
from ovos_plugin_manager.metadata_transformers import find_metadata_transformer_plugins
from ovos_plugin_manager.text_transformers import find_utterance_transformer_plugins
from ovos_plugin_manager.transformer_services import (
    IntentTransformersService as _IntentTransformersService,
    MetadataTransformersService as _MetadataTransformersService,
    UtteranceTransformersService as _UtteranceTransformersService)


class UtteranceTransformersService(_UtteranceTransformersService):
    """Runs utterance transformers in OVOS-TRANSFORM §4 ascending priority
    order: a plugin of priority 1 runs first."""

    def __init__(self, bus, config: Optional[dict] = None):
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_utterance_transformer_plugins().items()


class MetadataTransformersService(_MetadataTransformersService):
    """Runs metadata transformers in OVOS-TRANSFORM §4 ascending priority
    order: a plugin of priority 1 runs first."""

    def __init__(self, bus, config: Optional[dict] = None):
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_metadata_transformer_plugins().items()


class IntentTransformersService(_IntentTransformersService):
    """Runs intent transformers in OVOS-TRANSFORM §4 ascending priority
    order: a plugin of priority 1 runs first."""

    def __init__(self, bus, config: Optional[dict] = None):
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_intent_transformer_plugins().items()
