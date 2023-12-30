from ovos_workshop.intents import IntentBuilder
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from ovos_bus_client.session import SessionManager, Session


class OldStopSkill(OVOSSkill):

    def initialize(self):
        self.active = False

    @intent_handler(IntentBuilder("OldWorldIntent").require("HelloWorldKeyword"))
    def handle_hello_world_intent(self, message):
        self.speak_dialog("hello.world")
        self.active = True

    def stop(self):
        if self.active:
            self.speak("stop")
            self.active = False
            return True
        return False
