from ovos_workshop.skills.fallback import FallbackSkill
from ovos_workshop.decorators import fallback_handler


class UnknownSkill(FallbackSkill):

    @fallback_handler(priority=100)
    def handle_fallback(self, message):
        utterance = message.data['utterance'].lower()

        try:
            self.report_metric('failed-intent', {'utterance': utterance})
        except Exception:
            self.log.exception('Error reporting metric')

        for i in ['question', 'who.is', 'why.is']:
            if self.voc_match(utterance, i):
                self.log.debug('Fallback type: ' + i)
                self.speak_dialog(i)
                break
        else:
            self.speak_dialog('unknown')
        return True
