import time

from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill


class SlowFallbackSkill(FallbackSkill):

    @fallback_handler(priority=20)
    def handle_fallback(self, message):
        while True:  # busy skill
            time.sleep(0.1)
        self.speak("SLOW")
        return True
