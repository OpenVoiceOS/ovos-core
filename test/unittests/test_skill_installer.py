from unittest.mock import Mock

import pytest

from ovos_bus_client import Message
from ovos_core.skill_installer import SkillsStore


class MessageBusMock:
    """Replaces actual message bus calls in unit tests.

    The message bus should not be running during unit tests so mock it
    out in a way that makes it easy to test code that calls it.
    """

    def __init__(self):
        self.message_types = []
        self.message_data = []
        self.event_handlers = []

    def emit(self, message):
        self.message_types.append(message.msg_type)
        self.message_data.append(message.data)

    def on(self, event, _):
        self.event_handlers.append(event)

    def remove(self, event, _):
        self.event_handlers.remove(event)

    def once(self, event, _):
        self.event_handlers.append(event)

    def wait_for_response(self, message):
        self.emit(message)


@pytest.fixture(scope="function", autouse=True)
def skills_store(request):
    config = getattr(request, 'param', {})
    return SkillsStore(bus=MessageBusMock(), config=config)


def test_shutdown(skills_store):
    assert skills_store.shutdown() is None


def test_play_error_sound(skills_store):
    skills_store.play_error_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/error.mp3"
    }
    assert skills_store.bus.message_types[-1] == "mycroft.audio.play_sound"


@pytest.mark.parametrize("skills_store", [{"sounds": {"pip_error": "snd/custom_error.mp3"}}], indirect=True)
def test_play_error_sound_custom(skills_store):
    skills_store.play_error_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/custom_error.mp3"
    }
    assert skills_store.bus.message_types[-1] == "mycroft.audio.play_sound"


def test_play_success_sound(skills_store):
    skills_store.play_success_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/acknowledge.mp3"
    }
    assert skills_store.bus.message_types[-1] == "mycroft.audio.play_sound"


@pytest.mark.parametrize("skills_store", [{"sounds": {"pip_success": "snd/custom_success.mp3"}}], indirect=True)
def test_play_success_sound_custom(skills_store):
    skills_store.play_success_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/custom_success.mp3"
    }
    assert skills_store.bus.message_types[-1] == "mycroft.audio.play_sound"


def test_pip_install_no_packages(skills_store):
    # TODO: This method should be refactored in 0.1.0 for easier unit testing
    skills_store.play_error_sound = Mock()
    res = skills_store.pip_install([])
    assert res is False
    skills_store.play_error_sound.assert_called_once()


def test_pip_install_no_constraints(skills_store):
    skills_store.play_error_sound = Mock()
    res = skills_store.pip_install(["foo", "bar"], constraints="not/real")
    assert res is False
    skills_store.play_error_sound.assert_called_once()


def test_pip_install_happy_path():
    # TODO: This method should be refactored in 0.1.0 for easier unit testing
    assert True


def test_pip_uninstall_no_packages(skills_store):
    # TODO: This method should be refactored in 0.1.0 for easier unit testing
    skills_store.play_error_sound = Mock()
    res = skills_store.pip_uninstall([])
    assert res is False
    skills_store.play_error_sound.assert_called_once()


def test_pip_uninstall_no_constraints(skills_store):
    skills_store.play_error_sound = Mock()
    res = skills_store.pip_uninstall(["foo", "bar"], constraints="not/real")
    assert res is False
    skills_store.play_error_sound.assert_called_once()


def test_pip_uninstall_happy_path():
    # TODO: This method should be refactored in 0.1.0 for easier unit testing
    assert True


def test_validate_skill(skills_store):
    assert skills_store.validate_skill("https://github.com/openvoiceos/skill-foo") is True
    assert skills_store.validate_skill("https://gitlab.com/foo/skill-bar") is False
    assert skills_store.validate_skill("literally-anything-else") is False


@pytest.mark.parametrize('skills_store', [{"allow_pip": False}], indirect=True)
def test_handle_install_skill_not_allowed(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.validate_skill = Mock()
    skills_store.handle_install_skill(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf"}
    skills_store.validate_skill.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_skill_not_from_github(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.handle_install_skill(Message(msg_type="test", data={"url": "beautifulsoup4"}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "skill url validation failed"}


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_skill_from_github(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock(return_value=True)
    skills_store.handle_install_skill(
        Message(msg_type="test", data={"url": "https://github.com/OpenVoiceOS/skill-foo"}))
    skills_store.play_error_sound.assert_not_called()
    skills_store.pip_install.assert_called_once_with(["git+https://github.com/OpenVoiceOS/skill-foo"])
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.complete"
    assert skills_store.bus.message_data[-1] == {}


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_skill_from_github_failure(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock(return_value=False)
    skills_store.handle_install_skill(
        Message(msg_type="test", data={"url": "https://github.com/OpenVoiceOS/skill-foo"}))
    skills_store.play_error_sound.assert_not_called()
    skills_store.pip_install.assert_called_once_with(["git+https://github.com/OpenVoiceOS/skill-foo"])
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.failed"


@pytest.mark.parametrize('skills_store', [{"allow_pip": False}], indirect=True)
def test_handle_uninstall_skill_not_allowed(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.handle_uninstall_skill(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf"}


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_uninstall_skill(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.handle_uninstall_skill(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "not implemented"}


@pytest.mark.parametrize('skills_store', [{"allow_pip": False}], indirect=True)
def test_handle_install_python_not_allowed(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock()
    skills_store.handle_install_python(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.pip.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf"}
    skills_store.pip_install.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_python_no_packages(skills_store):
    skills_store.pip_install = Mock()
    skills_store.handle_install_python(Message(msg_type="test", data={}))
    assert skills_store.bus.message_types[-1] == "ovos.pip.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "no packages to install"}
    skills_store.pip_install.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_python_success(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock()
    packages = ["requests", "fastapi"]
    skills_store.handle_install_python(Message(msg_type="test", data={"packages": packages}))
    skills_store.play_error_sound.assert_not_called()
    skills_store.pip_install.assert_called_once_with(packages)
    assert skills_store.bus.message_types[-1] == "ovos.pip.install.complete"
    assert skills_store.bus.message_data[-1] == {}


@pytest.mark.parametrize('skills_store', [{"allow_pip": False}], indirect=True)
def test_handle_uninstall_python_not_allowed(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_uninstall = Mock()
    skills_store.handle_uninstall_python(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.pip.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf"}
    skills_store.pip_uninstall.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_uninstall_python_no_packages(skills_store):
    skills_store.pip_uninstall = Mock()
    skills_store.handle_uninstall_python(Message(msg_type="test", data={}))
    assert skills_store.bus.message_types[-1] == "ovos.pip.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "no packages to install"}
    skills_store.pip_uninstall.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_uninstall_python_success(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_uninstall = Mock()
    packages = ["requests", "fastapi"]
    skills_store.handle_uninstall_python(Message(msg_type="test", data={"packages": packages}))
    skills_store.play_error_sound.assert_not_called()
    skills_store.pip_uninstall.assert_called_once_with(packages)
    assert skills_store.bus.message_types[-1] == "ovos.pip.uninstall.complete"
    assert skills_store.bus.message_data[-1] == {}


if __name__ == "__main__":
    pytest.main()
