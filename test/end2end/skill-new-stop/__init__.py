from ovos_workshop.intents import IntentBuilder
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill
from ovos_bus_client.session import SessionManager, Session


class NewStopSkill(OVOSSkill):

    def initialize(self):
        self.active = []

    @intent_handler(IntentBuilder("NewWorldIntent").require("HelloWorldKeyword"))
    def handle_hello_world_intent(self, message):
        self.speak_dialog("hello.world")
        sess = SessionManager.get(message)
        self.active.append(sess.session_id)

    def stop_session(self, sess: Session):
        if sess.session_id in self.active:
            self.speak(f"stop {sess.session_id}")
            self.active.remove(sess.session_id)
            return True
        return False

    def stop(self):
        self.speak("old stop called")
