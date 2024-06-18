import time

from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill


class SlowFallbackSkill(FallbackSkill):

    @fallback_handler(priority=20)
    def handle_fallback(self, message):
        time.sleep(20)
        self.speak("SLOW")
        return True
