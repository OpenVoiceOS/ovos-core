from ovos_workshop.skills.common_query_skill import CommonQuerySkill, CQSMatchLevel


class UnWikiSkill(CommonQuerySkill):

    # common query integration
    def CQS_match_query_phrase(self, utt):
        response = "42"
        return (utt, CQSMatchLevel.EXACT, response,
                {'query': utt, 'answer': response})

    def CQS_action(self, phrase, data):
        """ If selected show gui """
        self.speak("selected")
