from time import sleep

from ovos_workshop.decorators import killable_intent, intent_handler
from ovos_workshop.skills.ovos import OVOSSkill


class TestAbortSkill(OVOSSkill):
    """
    send "mycroft.skills.abort_question" and confirm only get_response is aborted
    send "mycroft.skills.abort_execution" and confirm the full intent is aborted, except intent3
    send "my.own.abort.msg" and confirm intent3 is aborted
    say "stop" and confirm all intents are aborted
    """

    def initialize(self):
        self.stop_called = False
        self._converse = False
        self._converse_deactivate = False
        self.items = []
        self.bus.on("test_activate", self.do_activate)
        self.bus.on("test_deactivate", self.do_deactivate)
        self.bus.on("converse_deactivate", self.do_deactivate_converse)

    def do_deactivate_converse(self, message):
        self._converse_deactivate = True

    def do_activate(self, message):
        self.activate()

    def do_deactivate(self, message):
        self.deactivate()

    @intent_handler("deactivate.intent")
    def handle_deactivated(self, message):
        self.deactivate()
        self.speak("deactivated")

    @intent_handler("converse_on.intent")
    def handle_converse_on(self, message):
        self._converse = True
        self.speak("on")

    @intent_handler("converse_off.intent")
    def handle_converse_off(self, message):
        self._converse = False
        self.speak("off")

    def handle_intent_aborted(self):
        self.speak("I am dead")

    @intent_handler("test_get_response.intent")
    def handle_test_get_response(self, message):
        ans = self.get_response("get", num_retries=1)
        self.speak(ans or "ERROR")

    @intent_handler("test_get_response3.intent")
    def handle_test_get_response3(self, message):
        ans = self.get_response(num_retries=3)
        self.speak(ans or "ERROR")

    @intent_handler("test_get_response_cascade.intent")
    def handle_test_get_response_cascade(self, message):
        quit = False
        self.items = []
        self.speak("give me items", wait=True)
        while not quit:
            response = self.get_response(num_retries=0)
            if response is None:
                quit = True
            else:
                self.items.append(response)
        self.bus.emit(message.forward("skill_items", {"items": self.items}))

    @killable_intent(callback=handle_intent_aborted)
    @intent_handler("test.intent")
    def handle_test_abort_intent(self, message):
        self.stop_called = False
        self.my_special_var = "changed"
        while True:
            sleep(1)
            self.speak("still here")

    @intent_handler("test2.intent")
    @killable_intent(callback=handle_intent_aborted)
    def handle_test_get_response_intent(self, message):
        self.stop_called = False
        self.my_special_var = "CHANGED"
        ans = self.get_response("question", num_retries=99999)
        self.log.debug("get_response returned: " + str(ans))
        if ans is None:
            self.speak("question aborted")

    @killable_intent(msg="my.own.abort.msg", callback=handle_intent_aborted)
    @intent_handler("test3.intent")
    def handle_test_msg_intent(self, message):
        self.stop_called = False
        if self.my_special_var != "default":
            self.speak("someone forgot to cleanup")
        while True:
            sleep(1)
            self.speak("you can't abort me")

    def stop(self):
        self.stop_called = True

    def converse(self, message):
        if self._converse_deactivate:
            self.deactivate()
            self._converse_deactivate = False
            return True
        return self._converse
