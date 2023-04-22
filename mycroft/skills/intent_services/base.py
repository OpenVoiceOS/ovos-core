from ovos_config import Configuration


class IntentService:
    def __init__(self, bus=None, config=None):
        self.bus = bus
        self.config = config or Configuration().get("intents", {})
        if bus:
            self.bind(bus)

    def bind(self, bus=None):
        self.bus = bus or self.bus
        self.register_bus_handlers()
        self.register_compat_bus_handlers()

    def register_bus_handlers(self):
        pass

    def register_compat_bus_handlers(self):
        """mycroft compatible namespaces"""
        pass
