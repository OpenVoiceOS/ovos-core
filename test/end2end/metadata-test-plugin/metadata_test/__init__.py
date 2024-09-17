from typing import Optional

from ovos_plugin_manager.templates.transformers import MetadataTransformer


class MetadataPlugin(MetadataTransformer):

    def __init__(self, name="ovos-metadata-test-plugin", priority=15):
        super().__init__(name, priority)

    def transform(self, context: Optional[dict] = None) -> dict:
        return {"metadata": "test"}
