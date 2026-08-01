from unittest.mock import Mock, patch, MagicMock

import pytest

from ovos_bus_client import Message
from ovos_spec_tools import SpecMessage
from ovos_core.skill_installer import SkillsStore


def _make_github_response(status_code: int = 200, file_names: list = None,
                          ok: bool = True) -> MagicMock:
    """Build a fake requests.Response for the GitHub contents API."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = ok
    if file_names is not None:
        resp.json.return_value = [{"name": n} for n in file_names]
    else:
        resp.json.return_value = []
    return resp


def _make_manifest_response(text: str, ok: bool = True) -> MagicMock:
    """Build a fake requests.Response for a raw manifest file fetch."""
    resp = MagicMock()
    resp.ok = ok
    resp.text = text
    return resp


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
    assert skills_store.bus.message_types[-1] == SpecMessage.AUDIO_PLAY_SOUND


@pytest.mark.parametrize("skills_store", [{"sounds": {"pip_error": "snd/custom_error.mp3"}}], indirect=True)
def test_play_error_sound_custom(skills_store):
    skills_store.play_error_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/custom_error.mp3"
    }
    assert skills_store.bus.message_types[-1] == SpecMessage.AUDIO_PLAY_SOUND


def test_play_success_sound(skills_store):
    skills_store.play_success_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/acknowledge.mp3"
    }
    assert skills_store.bus.message_types[-1] == SpecMessage.AUDIO_PLAY_SOUND


@pytest.mark.parametrize("skills_store", [{"sounds": {"pip_success": "snd/custom_success.mp3"}}], indirect=True)
def test_play_success_sound_custom(skills_store):
    skills_store.play_success_sound()
    assert skills_store.bus.message_data[-1] == {
        "uri": "snd/custom_success.mp3"
    }
    assert skills_store.bus.message_types[-1] == SpecMessage.AUDIO_PLAY_SOUND


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


@pytest.mark.parametrize("requested", ["ovos-core", "ovos_core", "OVOS-Core", "ovos.core"])
def test_pip_uninstall_protected_package_separator_and_case_variants(skills_store, requested):
    """The protected-package guard must reject "-", "_" and "." separator
    variants, and case variants, of a protected name -- not just the exact
    spelling used in the constraints list (pip/PyPI treat them as the same
    distribution, per PEP 503)."""
    skills_store.play_error_sound = Mock()
    # bypass the constraints-file existence check so we exercise the
    # built-in default protected-package list ("ovos-core", ...)
    skills_store.validate_constraints = Mock(return_value=True)
    res = skills_store.pip_uninstall([requested], constraints="not/a/real/constraints/path")
    assert res is False
    skills_store.play_error_sound.assert_called_once()


def test_validate_skill_non_github_urls(skills_store):
    """Non-GitHub URLs are always rejected without any network call."""
    assert skills_store.validate_skill("https://gitlab.com/foo/skill-bar") is False
    assert skills_store.validate_skill("literally-anything-else") is False
    assert skills_store.validate_skill("http://github.com/foo/bar") is False  # must be https


def test_validate_skill_missing_repo_segment(skills_store):
    """URLs with fewer than two path segments after github.com are rejected."""
    assert skills_store.validate_skill("https://github.com/openvoiceos") is False


@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_valid_ovos_skill(mock_get, skills_store):
    """A repo with pyproject.toml and no legacy class names is accepted."""
    mock_get.side_effect = [
        _make_github_response(file_names=["pyproject.toml", "README.md"]),
        _make_manifest_response("[tool.poetry]\nname = 'ovos-skill-foo'"),
    ]
    assert skills_store.validate_skill("https://github.com/openvoiceos/skill-foo") is True


@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_repo_not_found(mock_get, skills_store):
    """A 404 from the GitHub API means the repo does not exist — reject."""
    mock_get.return_value = _make_github_response(status_code=404, ok=False)
    assert skills_store.validate_skill("https://github.com/openvoiceos/nonexistent") is False

@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_network_error_fail_open(mock_get, skills_store):
    """If GitHub is unreachable (exception), validate_skill returns True (fail open)."""
    mock_get.side_effect = ConnectionError("no network")
    assert skills_store.validate_skill("https://github.com/openvoiceos/skill-foo") is True


@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_unexpected_api_error_fail_open(mock_get, skills_store):
    """A non-404 API error (e.g. 503) returns True (fail open)."""
    mock_get.return_value = _make_github_response(status_code=503, ok=False)
    assert skills_store.validate_skill("https://github.com/openvoiceos/skill-foo") is True


@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_setup_cfg_valid(mock_get, skills_store):
    """setup.cfg without legacy class names is accepted."""
    mock_get.side_effect = [
        _make_github_response(file_names=["setup.cfg", "README.md"]),
        _make_manifest_response("[metadata]\nname = ovos-skill-foo"),
    ]
    assert skills_store.validate_skill("https://github.com/openvoiceos/skill-foo") is True


@patch("ovos_core.skill_installer.requests.get")
def test_validate_skill_dot_git_suffix_stripped(mock_get, skills_store):
    """.git suffix in URL is stripped when constructing the API call."""
    mock_get.side_effect = [
        _make_github_response(file_names=["pyproject.toml"]),
        _make_manifest_response("name = 'ovos-skill-foo'"),
    ]
    result = skills_store.validate_skill("https://github.com/openvoiceos/skill-foo.git")
    assert result is True
    # Verify .git was stripped: repo segment in API URL should be 'skill-foo', not 'skill-foo.git'
    call_url = mock_get.call_args_list[0][0][0]
    assert "skill-foo.git" not in call_url
    assert "skill-foo/contents/" in call_url


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
    skills_store.validate_skill = Mock(return_value=True)
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
    skills_store.validate_skill = Mock(return_value=True)
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
    # Test with no skill specified
    skills_store.handle_uninstall_skill(Message(msg_type="test", data={}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.uninstall.failed"
    assert skills_store.bus.message_data[-1]["error"] == "no packages to install"


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
