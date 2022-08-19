from adapt.intent import IntentBuilder

from mycroft.skills.common_query_skill import CommonQuerySkill, CQSMatchLevel
from mycroft.skills.core import intent_handler


class FakeWikiSkill(CommonQuerySkill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.displayed = False
        self.idx = 0
        self.results = []

    # explicit intents
    @intent_handler("search_fakewiki.intent")
    def handle_search(self, message):
        query = message.data["query"]
        self.ask_the_wiki(query)
        if self.results:
            self.speak_result()
        else:
            self.speak_dialog("no_answer")

    @intent_handler(IntentBuilder("FakeWikiMore").require("More").
                    require("FakeWikiKnows"))
    def handle_tell_more(self, message):
        """ Follow up query handler, "tell me more"."""
        self.speak_result()

    def speak_result(self):
        if self.idx + 1 > len(self.results):
            self.speak_dialog("thats all")
            self.remove_context("FakeWikiKnows")
            self.idx = 0
        else:
            self.display_fakewiki()
            ans = self.results[self.idx]
            self.speak(ans)
            self.idx += 1

    # common query integration
    def CQS_match_query_phrase(self, utt):
        self.log.debug("FakeWiki query: " + utt)
        response = self.ask_the_wiki(utt)[0]
        self.idx += 1  # spoken by common query framework
        return (utt, CQSMatchLevel.GENERAL, response,
                {'query': utt, 'answer': response})

    def CQS_action(self, phrase, data):
        """ If selected show gui """
        self.display_fakewiki()

    # fakewiki integration
    def ask_the_wiki(self, query):
        # context for follow up questions
        self.set_context("FakeWikiKnows", query)
        self.idx = 0
        self.results = ["answer 1", "answer 2"]
        return self.results

    def display_fakewiki(self):
        self.displayed = True


def create_skill():
    return FakeWikiSkill()
