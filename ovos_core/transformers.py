from typing import Optional, List

from ovos_plugin_manager.metadata_transformers import find_metadata_transformer_plugins
from ovos_plugin_manager.templates.transformers import UtteranceTransformer
from ovos_plugin_manager.text_transformers import find_utterance_transformer_plugins

from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG


class UtteranceTransformersService:

    def __init__(self, bus, config=None):
        self.config_core = config or {}
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        self.config = self.config_core.get("utterance_transformers") or {
            "ovos-lf-utterance-normalizer": {}
        }
        self.load_plugins()

    def load_plugins(self):
        for plug_name, plug in find_utterance_transformer_plugins().items():
            if plug_name in self.config:
                # if disabled skip it
                if not self.config[plug_name].get("active", True):
                    continue
                try:
                    self.loaded_plugins[plug_name] = plug()
                    LOG.info(f"loaded utterance transformer plugin: {plug_name}")
                except Exception as e:
                    LOG.error(e)
                    LOG.exception(f"Failed to load utterance transformer plugin: {plug_name}")

    @property
    def plugins(self):
        """
        Return loaded transformers in priority order, such that modules with a
        higher `priority` rank are called first and changes from lower ranked
        transformers are applied last

        A plugin of `priority` 1 will override any existing context keys and
        will be the last to modify utterances`
        """
        return sorted(self.loaded_plugins.values(),
                      key=lambda k: k.priority, reverse=True)

    def shutdown(self):
        for module in self.plugins:
            try:
                module.shutdown()
            except:
                pass

    def transform(self, utterances: List[str], context: Optional[dict] = None):
        context = context or {}

        for module in self.plugins:
            try:
                utterances, data = module.transform(utterances, context)
                LOG.debug(f"{module.name}: {data}")
                context = merge_dict(context, data)
            except Exception as e:
                LOG.warning(f"{module.name} transform exception: {e}")
        return utterances, context


class MetadataTransformersService:

    def __init__(self, bus, config=None):
        self.config_core = config or {}
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        self.config = self.config_core.get("metadata_transformers") or {}
        self.load_plugins()

    def load_plugins(self):
        for plug_name, plug in find_metadata_transformer_plugins().items():
            if plug_name in self.config:
                # if disabled skip it
                if not self.config[plug_name].get("active", True):
                    continue
                try:
                    self.loaded_plugins[plug_name] = plug()
                    LOG.info(f"loaded metadata transformer plugin: {plug_name}")
                except Exception as e:
                    LOG.error(e)
                    LOG.exception(f"Failed to load metadata transformer plugin: {plug_name}")

    @property
    def plugins(self):
        """
        Return loaded transformers in priority order, such that modules with a
        higher `priority` rank are called first and changes from lower ranked
        transformers are applied last.

        A plugin of `priority` 1 will override any existing context keys
        """
        return sorted(self.loaded_plugins.values(),
                      key=lambda k: k.priority, reverse=True)

    def shutdown(self):
        for module in self.plugins:
            try:
                module.shutdown()
            except:
                pass

    def transform(self, context: Optional[dict] = None):
        context = context or {}

        for module in self.plugins:
            try:
                data = module.transform(context)
                LOG.debug(f"{module.name}: {data}")
                context = merge_dict(context, data)
            except Exception as e:
                LOG.warning(f"{module.name} transform exception: {e}")
        return context


class UtteranceNormalizer(UtteranceTransformer):

    def __init__(self, name="ovos-lf-utterance-normalizer", priority=1):
        super().__init__(name, priority)

    @staticmethod
    def strip_punctuation(utterance: str):
        return utterance.rstrip('.').rstrip('?').rstrip('!').rstrip(',').rstrip(';')

    def transform(self, utterances: List[str],
                  context: Optional[dict] = None) -> (list, dict):
        context = context or {}
        norm = [self.strip_punctuation(u) for u in utterances] + utterances
        try:
            # TODO - move to ovos-classifiers when it gets it's first stable release
            # make ovos-lf provide this plugin with a lower priority afterwards
            from lingua_franca.parse import normalize
            lang = context.get("lang") or self.config.get("lang", "en-us")
            norm += [normalize(u, lang=lang, remove_articles=False) for u in norm] + \
                    [normalize(u, lang=lang, remove_articles=True) for u in norm]
        except ImportError:
            LOG.warning("lingua_franca not installed")
        except:
            LOG.exception("lingua_franca utterance normalization failed")

        return list(set(norm)), context
