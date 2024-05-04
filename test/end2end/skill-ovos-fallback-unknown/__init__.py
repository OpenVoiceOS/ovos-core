from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill


class UnknownSkill(FallbackSkill):
    def initialize(self):
        self._fallback_deactivate = False
        self.add_event("fallback_deactivate",
                       self.do_deactivate_fallback)

    def do_deactivate_fallback(self, message):
        self._fallback_deactivate = True

    @fallback_handler(priority=100)
    def handle_fallback(self, message):
        self.speak_dialog('unknown')
        if self._fallback_deactivate:
            self._fallback_deactivate = False
            self.deactivate()
        return True
