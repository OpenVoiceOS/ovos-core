from ovos_utils.intents import IntentBuilder
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill


class ScheduleSkill(OVOSSkill):

    def handle_event(self, message):
        self.speak_dialog("trigger")

    @intent_handler(IntentBuilder("ScheduleIntent").require("Schedule"))
    def handle_sched_intent(self, message):
        self.speak_dialog("done")
        self.schedule_event(self.handle_event, 3, name="my_event")
