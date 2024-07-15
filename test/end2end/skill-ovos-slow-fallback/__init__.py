import time

from ovos_workshop.decorators import fallback_handler
from ovos_workshop.skills.fallback import FallbackSkill


class SlowFallbackSkill(FallbackSkill):
    """test skill that would block
    converse/fallback forever if not killed"""

    @fallback_handler(priority=20)
    def handle_fallback(self, message):
        while True:  # busy skill
            time.sleep(0.1)
        return True

    def converse(self, message):
        while True:  # busy skill
            time.sleep(0.1)
        return True
