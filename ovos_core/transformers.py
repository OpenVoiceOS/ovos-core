from typing import Optional, List
from ovos_config import Configuration
from ovos_plugin_manager.intent_transformers import find_intent_transformer_plugins
from ovos_plugin_manager.metadata_transformers import find_metadata_transformer_plugins
from ovos_plugin_manager.text_transformers import find_utterance_transformer_plugins

from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_utils.json_helper import merge_dict
from ovos_utils.log import LOG


class UtteranceTransformersService:

    def __init__(self, bus, config=None):
        self.config_core = config or Configuration()
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        self.config = self.config_core.get("utterance_transformers") or {}
        self.load_plugins()

    @staticmethod
    def find_plugins():
        return find_utterance_transformer_plugins().items()

    def load_plugins(self):
        for plug_name, plug in self.find_plugins():
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
                _safe = {k:v for k,v in data.items() if k != "session"}  # no leaking TTS/STT creds in logs    
                LOG.debug(f"{module.name}: {_safe}")
                context = merge_dict(context, data)
            except Exception as e:
                LOG.warning(f"{module.name} transform exception: {e}")
        return utterances, context


class MetadataTransformersService:

    def __init__(self, bus, config=None):
        self.config_core = config or Configuration()
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        self.config = self.config_core.get("metadata_transformers") or {}
        self.load_plugins()

    @staticmethod
    def find_plugins():
        return find_metadata_transformer_plugins().items()

    def load_plugins(self):
        for plug_name, plug in self.find_plugins():
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
        """
        Sequentially applies all loaded metadata transformer plugins to the provided context.

        Each plugin's `transform` method is called in order of descending priority, and the resulting data is merged into the context. Sensitive session data is excluded from debug logs. Exceptions raised by plugins are logged as warnings and do not interrupt the transformation process.

        Args:
            context: Optional dictionary containing metadata to be transformed.

        Returns:
            The updated context dictionary after all transformations.
        """
        context = context or {}

        for module in self.plugins:
            try:
                data = module.transform(context)                
                _safe = {k:v for k,v in data.items() if k != "session"}  # no leaking TTS/STT creds in logs    
                LOG.debug(f"{module.name}: {_safe}")
                context = merge_dict(context, data)
            except Exception as e:
                LOG.warning(f"{module.name} transform exception: {e}")
        return context


class IntentTransformersService:

    def __init__(self, bus, config=None):
        """
        Initializes the IntentTransformersService with the provided message bus and configuration.

        Loads and prepares intent transformer plugins based on the configuration, making them ready for use.
        """
        self.config_core = config or Configuration()
        self.loaded_plugins = {}
        self.has_loaded = False
        self.bus = bus
        self.config = self.config_core.get("intent_transformers") or {}
        self.load_plugins()

    @staticmethod
    def find_plugins():
        """
        Discovers and returns available intent transformer plugins.

        Returns:
            An iterable of (plugin_name, plugin_class) pairs for all discovered intent transformer plugins.
        """
        return find_intent_transformer_plugins().items()

    def load_plugins(self):
        """
        Loads and initializes enabled intent transformer plugins based on the configuration.

        Plugins marked as inactive in the configuration are skipped. Successfully loaded plugins are added to the internal registry, while failures are logged without interrupting the loading process.
        """
        for plug_name, plug in self.find_plugins():
            if plug_name in self.config:
                # if disabled skip it
                if not self.config[plug_name].get("active", True):
                    continue
                try:
                    self.loaded_plugins[plug_name] = plug()
                    self.loaded_plugins[plug_name].bind(self.bus)
                    LOG.info(f"loaded intent transformer plugin: {plug_name}")
                except Exception as e:
                    LOG.error(e)
                    LOG.exception(f"Failed to load intent transformer plugin: {plug_name}")

    @property
    def plugins(self):
        """
        Returns the loaded intent transformer plugins sorted by priority.
        """
        return sorted(self.loaded_plugins.values(),
                      key=lambda k: k.priority, reverse=True)

    def shutdown(self):
        """
        Shuts down all loaded plugins, suppressing any exceptions raised during shutdown.
        """
        for module in self.plugins:
            try:
                module.shutdown()
            except:
                pass

    def transform(self, intent: IntentHandlerMatch) -> IntentHandlerMatch:
        """
        Sequentially applies all loaded intent transformer plugins to the given intent object.

        Each plugin's `transform` method is called in order of priority. Exceptions raised by individual plugins are logged as warnings, and processing continues with the next plugin. The final, transformed intent object is returned.

        Args:
            intent: The intent match object to be transformed.

        Returns:
            The transformed intent match object after all plugins have been applied.
        """
        for module in self.plugins:
            try:
                intent = module.transform(intent)
                LOG.debug(f"{module.name}: {intent}")
            except Exception as e:
                LOG.warning(f"{module.name} transform exception: {e}")
        return intent
