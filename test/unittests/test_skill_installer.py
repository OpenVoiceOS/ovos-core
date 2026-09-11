from unittest.mock import Mock, patch, MagicMock

import pytest

from ovos_bus_client import Message
from ovos_core.skill_installer import SkillsStore, FAILURE_DETAIL_CHARS


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
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf", "detail": ""}
    skills_store.validate_skill.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_skill_not_from_github(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.handle_install_skill(Message(msg_type="test", data={"url": "beautifulsoup4"}))
    skills_store.play_error_sound.assert_called_once()
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "skill url validation failed", "detail": ""}


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
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf", "detail": ""}


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
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf", "detail": ""}
    skills_store.pip_install.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_python_no_packages(skills_store):
    skills_store.pip_install = Mock()
    skills_store.handle_install_python(Message(msg_type="test", data={}))
    assert skills_store.bus.message_types[-1] == "ovos.pip.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "no packages to install", "detail": ""}
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
    assert skills_store.bus.message_data[-1] == {"error": "pip disabled in mycroft.conf", "detail": ""}
    skills_store.pip_uninstall.assert_not_called()


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_uninstall_python_no_packages(skills_store):
    skills_store.pip_uninstall = Mock()
    skills_store.handle_uninstall_python(Message(msg_type="test", data={}))
    assert skills_store.bus.message_types[-1] == "ovos.pip.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "no packages to install", "detail": ""}
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


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_python_pip_raises(skills_store):
    # pip_install raises RuntimeError on a genuine pip failure (non-zero
    # exit); the handler must still emit a .failed reply instead of
    # letting the exception propagate and leaving the caller hanging.
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock(side_effect=RuntimeError("pip exited with status 1"))
    packages = ["some-broken-package"]
    skills_store.handle_install_python(Message(msg_type="test", data={"packages": packages}))
    skills_store.pip_install.assert_called_once_with(packages)
    assert skills_store.bus.message_types[-1] == "ovos.pip.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "error in pip subprocess",
                                                 "detail": "pip exited with status 1"}


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_uninstall_python_pip_raises(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_uninstall = Mock(side_effect=RuntimeError("pip exited with status 1"))
    packages = ["some-broken-package"]
    skills_store.handle_uninstall_python(Message(msg_type="test", data={"packages": packages}))
    skills_store.pip_uninstall.assert_called_once_with(packages)
    assert skills_store.bus.message_types[-1] == "ovos.pip.uninstall.failed"
    assert skills_store.bus.message_data[-1] == {"error": "error in pip subprocess",
                                                 "detail": "pip exited with status 1"}


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_handle_install_skill_pip_raises(skills_store):
    skills_store.play_error_sound = Mock()
    skills_store.pip_install = Mock(side_effect=RuntimeError("pip exited with status 1"))
    skills_store.validate_skill = Mock(return_value=True)
    skills_store.handle_install_skill(
        Message(msg_type="test", data={"url": "https://github.com/OpenVoiceOS/skill-foo"}))
    skills_store.pip_install.assert_called_once_with(["git+https://github.com/OpenVoiceOS/skill-foo"])
    assert skills_store.bus.message_types[-1] == "ovos.skills.install.failed"
    assert skills_store.bus.message_data[-1] == {"error": "error in pip subprocess",
                                                 "detail": "pip exited with status 1"}


# ---------------------------------------------------------------------------
# the installer's output reaches the .failed reply
# ---------------------------------------------------------------------------

def _fake_uv(tmp_path, stderr_text: str, exit_code: int = 1) -> str:
    """A stand-in for the uv binary that prints ``stderr_text`` and exits."""
    script = tmp_path / "uv"
    script.write_text("#!/usr/bin/env python3\n"
                      "import sys\n"
                      f"sys.stderr.write({stderr_text!r})\n"
                      f"sys.exit({exit_code})\n")
    script.chmod(0o755)
    return str(script)


def _store_with_fake_uv(tmp_path, monkeypatch, stderr_text: str) -> SkillsStore:
    """A store whose pip backend is a failing fake uv and whose constraints file exists."""
    monkeypatch.setattr(SkillsStore, "UV", _fake_uv(tmp_path, stderr_text))
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("")
    store = SkillsStore(bus=MessageBusMock(), config={"allow_pip": True, "constraints": str(constraints)})
    store.play_error_sound = Mock()
    return store


UNPUBLISHED = ("error: No solution found when resolving dependencies:\n"
               "  Because ovos-skill-foo==9.9.9 was not found in the package registry")


def test_failed_reply_carries_the_installers_output(tmp_path, monkeypatch):
    """A remote caller can tell "not published yet" from "conflict" only if the
    reply carries what pip or uv actually said."""
    store = _store_with_fake_uv(tmp_path, monkeypatch, UNPUBLISHED)

    store.handle_install_python(Message("ovos.pip.install", {"packages": ["ovos-skill-foo==9.9.9"]}))

    assert store.bus.message_types[-1] == "ovos.pip.install.failed"
    reply = store.bus.message_data[-1]
    assert reply["error"] == "error in pip subprocess"
    assert "ovos-skill-foo==9.9.9 was not found" in reply["detail"]
    store.play_error_sound.assert_called_once()


def test_every_pip_backed_failed_reply_carries_detail(tmp_path, monkeypatch):
    store = _store_with_fake_uv(tmp_path, monkeypatch, UNPUBLISHED)
    store.validate_skill = Mock(return_value=True)

    store.handle_install_skill(Message("ovos.skills.install", {"url": "https://github.com/OpenVoiceOS/skill-foo"}))
    store.handle_uninstall_python(Message("ovos.pip.uninstall", {"packages": ["ovos-skill-foo"]}))
    store.handle_uninstall_skill(Message("ovos.skills.uninstall", {"skill": "skill-foo.openvoiceos"}))

    assert store.bus.message_types[-3:] == ["ovos.skills.install.failed",
                                            "ovos.pip.uninstall.failed",
                                            "ovos.skills.uninstall.failed"]
    for reply in store.bus.message_data[-3:]:
        assert "ovos-skill-foo" in reply["detail"]
        assert reply["error"]


def test_refusals_before_pip_runs_carry_an_empty_detail():
    """The reply shape is stable: ``detail`` is present and empty when pip never ran."""
    store = SkillsStore(bus=MessageBusMock(), config={"allow_pip": True})
    store.play_error_sound = Mock()

    store.handle_install_python(Message("ovos.pip.install", {"packages": []}))

    assert store.bus.message_types[-1] == "ovos.pip.install.failed"
    assert store.bus.message_data[-1] == {"error": "no packages to install", "detail": ""}


def test_pip_output_is_still_logged_when_print_logs_is_true(tmp_path, monkeypatch):
    store = _store_with_fake_uv(tmp_path, monkeypatch, "first line\nsecond line\n")

    with patch("ovos_core.skill_installer.LOG") as log:
        with pytest.raises(RuntimeError) as raised:
            store.pip_install(["ovos-skill-foo"], print_logs=True)
    logged = [call.args[0] for call in log.info.call_args_list]
    assert "(pip) first line" in logged
    assert "(pip) second line" in logged
    assert str(raised.value) == "first line\nsecond line"

    with patch("ovos_core.skill_installer.LOG") as log:
        with pytest.raises(RuntimeError):
            store.pip_install(["ovos-skill-foo"], print_logs=False)
    assert not [call for call in log.info.call_args_list if "first line" in call.args[0]]


def test_detail_is_bounded_to_the_tail_of_the_output(tmp_path, monkeypatch):
    """A long resolver trace must not turn a bus reply into a multi-kilobyte
    payload; the end of the output is the part that explains the failure."""
    marker = "the reason is at the end"
    store = _store_with_fake_uv(tmp_path, monkeypatch, "x" * (3 * FAILURE_DETAIL_CHARS) + marker)

    store.handle_install_python(Message("ovos.pip.install", {"packages": ["ovos-skill-foo"]}))

    detail = store.bus.message_data[-1]["detail"]
    assert len(detail) == FAILURE_DETAIL_CHARS
    assert detail.endswith(marker)


if __name__ == "__main__":
    pytest.main()


# ---------------------------------------------------------------------------
# OVOS-INSTALL-1 §2.2 — data.service_name addresses one installer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_a_pip_request_for_another_service_is_ignored_in_silence(skills_store):
    """Naming another service, this one installs nothing and answers
    nothing: a decline from every installer would bury the real answer."""
    skills_store.pip_install = Mock(return_value=True)
    skills_store.handle_install_python(Message(
        "ovos.pip.install",
        {"packages": ["some-plugin"], "service_name": "ovos_audio"}))
    skills_store.pip_install.assert_not_called()
    assert skills_store.bus.message_types == []


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_a_pip_request_naming_the_skills_service_is_acted_on(skills_store):
    skills_store.pip_install = Mock(return_value=True)
    skills_store.handle_install_python(Message(
        "ovos.pip.install",
        {"packages": ["some-plugin"], "service_name": "ovos_core"}))
    skills_store.pip_install.assert_called_once()
    assert skills_store.bus.message_types == ["ovos.pip.install.complete"]


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_a_pip_request_naming_nobody_still_reaches_this_service(skills_store):
    """The guard that this change did not narrow the broadcast."""
    skills_store.pip_install = Mock(return_value=True)
    skills_store.handle_install_python(
        Message("ovos.pip.install", {"packages": ["some-plugin"]}))
    skills_store.pip_install.assert_called_once()
    assert skills_store.bus.message_types == ["ovos.pip.install.complete"]


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
@pytest.mark.parametrize('near_miss', ["OVOS_CORE", "ovos_core_extra", "ovos"])
def test_the_service_name_comparison_is_exact(skills_store, near_miss):
    skills_store.pip_install = Mock(return_value=True)
    skills_store.handle_install_python(Message(
        "ovos.pip.install",
        {"packages": ["p"], "service_name": near_miss}))
    skills_store.pip_install.assert_not_called()
    assert skills_store.bus.message_types == []


@pytest.mark.parametrize('skills_store', [{"allow_pip": True}], indirect=True)
def test_pip_uninstall_is_addressed_the_same_way(skills_store):
    skills_store.pip_uninstall = Mock(return_value=True)
    skills_store.handle_uninstall_python(Message(
        "ovos.pip.uninstall",
        {"packages": ["some-plugin"], "service_name": "ovos_audio"}))
    skills_store.pip_uninstall.assert_not_called()
    assert skills_store.bus.message_types == []


def test_no_suffixed_pip_topic_is_registered(skills_store):
    """OVOS-MSG-1 §2.1.1 keeps the target out of the topic, so the skills
    service never subscribes to a service-suffixed pip topic."""
    suffixed = [e for e in skills_store.bus.event_handlers
                if e.startswith("ovos.pip.") and e.count(".") > 2]
    assert suffixed == []
