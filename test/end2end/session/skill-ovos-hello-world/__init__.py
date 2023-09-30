from ovos_utils.intents import IntentBuilder
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill


class HelloWorldSkill(OVOSSkill):

    @intent_handler(IntentBuilder("HelloWorldIntent").require("HelloWorldKeyword"))
    def handle_hello_world_intent(self, message):
        self.speak_dialog("hello.world")
