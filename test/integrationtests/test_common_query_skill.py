from unittest import TestCase, mock

from ovos_bus_client.message import Message

from ovos_workshop.skills.common_query_skill import CommonQuerySkill

# TODO - move test to ovos-workshop

class AnyCallable:
    """Class matching any callable.

    Useful for assert_called_with arguments.
    """
    def __eq__(self, other):
        return callable(other)



class TestCommonQuerySkill(TestCase):
    def setUp(self):
        self.skill = CQSTest()
        self.bus = mock.Mock(name='bus')
        self.skill.bind(self.bus)
        self.skill.config_core = {'enclosure': {'platform': 'mycroft_mark_1'}}

    def test_lifecycle(self):
        """Test startup and shutdown."""
        skill = CQSTest()
        bus = mock.Mock(name='bus')
        skill.bind(bus)
        bus.on.assert_any_call('question:query', AnyCallable())
        bus.on.assert_any_call('question:action', AnyCallable())
        skill.shutdown()

    def test_common_test_skill_action(self):
        """Test that the optional action is triggered."""
        query_action = self.bus.on.call_args_list[-2][0][1]
        query_action(Message('query:action', data={
            'phrase': 'What\'s the meaning of life',
            'skill_id': 'asdf'}))
        self.skill.CQS_action.assert_not_called()
        query_action(Message('query:action', data={
            'phrase': 'What\'s the meaning of life',
            'skill_id': 'CQSTest'}))
        self.skill.CQS_action.assert_called_once_with(
            'What\'s the meaning of life', {})


class CQSTest(CommonQuerySkill):
    """Simple skill for testing the CommonQuerySkill"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.CQS_match_query_phrase = mock.Mock(name='match_phrase')
        self.CQS_action = mock.Mock(name='selected_action')
        self.skill_id = 'CQSTest'

    def CQS_match_query_phrase(self, phrase):
        pass

    def CQS_action(self, phrase, data):
        pass
