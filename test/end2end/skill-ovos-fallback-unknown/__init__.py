from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill


class UnknownSkill(FallbackSkill):

    @fallback_handler(priority=100)
    def handle_fallback(self, message):
        self.speak_dialog('unknown')
        return True
