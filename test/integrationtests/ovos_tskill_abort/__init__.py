from ovos_workshop.decorators import killable_intent
from ovos_workshop.skills.ovos import OVOSSkill
from ovos_workshop.decorators import intent_handler
from time import sleep


class TestAbortSkill(OVOSSkill):
    """
    send "mycroft.skills.abort_question" and confirm only get_response is aborted
    send "mycroft.skills.abort_execution" and confirm the full intent is aborted, except intent3
    send "my.own.abort.msg" and confirm intent3 is aborted
    say "stop" and confirm all intents are aborted
    """
    def __init__(self, *args, **kwargs):
        super(TestAbortSkill, self).__init__(*args, **kwargs)
        self.my_special_var = "default"
        self.stop_called = False

    def handle_intent_aborted(self):
        """
        Handles cleanup when an intent is aborted.
        
        Speaks a message indicating the intent was terminated and resets internal state to default values.
        """
        self.speak("I am dead")
        # handle any cleanup the skill might need, since intent was killed
        # at an arbitrary place of code execution some variables etc. might
        # end up in unexpected states
        self.my_special_var = "default"

    @killable_intent(callback=handle_intent_aborted)
    @intent_handler("test.intent")
    def handle_test_abort_intent(self, message):
        """
        Handles the 'test.intent' by entering a loop that repeatedly announces presence.
        
        This intent is designed to be abortable during execution. It sets internal state variables before entering an infinite loop, where it speaks "still here" every second until aborted.
        """
        self.stop_called = False
        self.my_special_var = "changed"
        while True:
            sleep(1)
            self.speak("still here")

    @intent_handler("test2.intent")
    @killable_intent(callback=handle_intent_aborted)
    def handle_test_get_response_intent(self, message):
        """
        Handles the 'test2.intent' by prompting the user for a response with high retry count.
        
        If the user aborts the prompt, announces that the question was aborted.
        """
        self.stop_called = False
        self.my_special_var = "CHANGED"
        ans = self.get_response("question", num_retries=99999)
        self.log.debug("get_response returned: " + str(ans))
        if ans is None:
            self.speak("question aborted")

    @killable_intent(msg="my.own.abort.msg", callback=handle_intent_aborted)
    @intent_handler("test3.intent")
    def handle_test_msg_intent(self, message):
        """
        Handles the 'test3.intent' intent and demonstrates abortion via a custom message trigger.
        
        If the internal state variable is not set to "default", notifies about missing cleanup. Then enters an infinite loop, periodically speaking a message, until externally aborted by the custom message trigger.
        """
        self.stop_called = False
        if self.my_special_var != "default":
            self.speak("someone forgot to cleanup")
        while True:
            sleep(1)
            self.speak("you can't abort me")

    def stop(self):
        self.stop_called = True


def create_skill():
    return TestAbortSkill()
