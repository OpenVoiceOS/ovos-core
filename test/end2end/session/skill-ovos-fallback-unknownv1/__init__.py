from ovos_workshop.skills.fallback import FallbackSkillV1
from ovos_workshop.decorators import fallback_handler


# explicitly use class with compat for older cores
# this is usually auto detected, just done here for unittests
class UnknownSkill(FallbackSkillV1):

    @fallback_handler(priority=100)
    def handle_fallback(self, message):
        self.speak_dialog('unknown')
        return True
