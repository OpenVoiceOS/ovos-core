from typing import Dict, FrozenSet, List, Optional

from ovos_config import Configuration
from ovos_plugin_manager.intent_transformers import find_intent_transformer_plugins
from ovos_plugin_manager.metadata_transformers import find_metadata_transformer_plugins
from ovos_plugin_manager.templates.transformers import TypedSlotsTransformer
from ovos_plugin_manager.text_transformers import find_utterance_transformer_plugins
from ovos_plugin_manager.transformer_services import (
    IntentTransformersService as _IntentTransformersService,
    MetadataTransformersService as _MetadataTransformersService,
    TransformersService as _TransformersService,
    UtteranceTransformersService as _UtteranceTransformersService)
from ovos_plugin_manager.typed_slots_transformers import find_typed_slots_transformer_plugins
from ovos_utils.log import LOG


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


class TypedSlotsTransformersService(_TransformersService):
    """Runs the OVOS-TRANSFORM-1 §3.7 typed-slots stage.

    The stage produces one map, so §4's ordering selects a single plugin
    instead of sequencing them: the first entry of an explicit order list
    where the deployment configures one, otherwise the lowest priority
    number loaded.
    """
    transformer_type = "typed_slots"
    config_section = "typed_slots_transformers"
    plugin_finder = staticmethod(find_typed_slots_transformer_plugins)

    def __init__(self, bus, config: Optional[dict] = None):
        self._selected = None
        config = config or Configuration()
        super().__init__(bus=bus, config=config)

    @classmethod
    def find_plugins(cls):
        return find_typed_slots_transformer_plugins().items()

    @property
    def selected(self) -> Optional[TypedSlotsTransformer]:
        """The one transformer §4's ordering places first, if any is loaded.

        Resolved once and kept, so an unresolvable tie is reported at
        selection time rather than on every utterance. A reload clears the
        sorted-plugin cache, which is the signal to select again.
        """
        if self._sorted_plugins is None:
            self._selected = None
        plugins = self.plugins
        if self._selected is None and plugins:
            self._selected = plugins[0]
            if (not isinstance(self.config.get("order"), list) and len(plugins) > 1
                    and plugins[1].priority == self._selected.priority):
                LOG.warning(
                    f"typed-slots transformers {self._selected.name!r} and "
                    f"{plugins[1].name!r} share priority {self._selected.priority}; "
                    f"the choice is stable but unspecified, configure an explicit "
                    f"'order' list (OVOS-TRANSFORM-1 §3.7)")
        return self._selected

    def transform(self, utterances: List[str], declared_types: FrozenSet[str],
                  session) -> Optional[Dict[str, List[dict]]]:
        """Compute the typed-slots map, or ``None`` when none was computed.

        ``None`` and an empty map are different answers: OVOS-INTENT-1 §5.6
        reads an absent map as "not computed" and an empty one as "computed
        and nothing found". A plugin that raises or returns the wrong shape
        is treated as having produced nothing (§7).
        """
        module = self.selected
        if module is None:
            return None
        try:
            typed_slots = module.transform(utterances, declared_types, session)
        except Exception as e:
            LOG.warning(f"{module.name} transform exception: {e}")
            return None
        if not isinstance(typed_slots, dict):
            LOG.warning(f"{module.name} returned wrong shape (expected a "
                        f"typed-slots map): {type(typed_slots)}; ignoring its output")
            return None
        return typed_slots
