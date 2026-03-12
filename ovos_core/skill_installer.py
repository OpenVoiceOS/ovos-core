import enum
import shutil
import sys
from importlib import reload
from os.path import exists
from subprocess import Popen, PIPE
from typing import Optional

import requests
from combo_lock import NamedLock
from ovos_bus_client import Message
from ovos_config.config import Configuration
from ovos_utils.log import LOG

import ovos_plugin_manager


class InstallError(str, enum.Enum):
    DISABLED = "pip disabled in mycroft.conf"
    PIP_ERROR = "error in pip subprocess"
    BAD_URL = "skill url validation failed"
    NO_PKGS = "no packages to install"


class SkillsStore:
    # default constraints to use if none are given
    DEFAULT_CONSTRAINTS = 'https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/refs/heads/main/constraints-stable.txt'
    PIP_LOCK = NamedLock("ovos_pip.lock")
    UV = shutil.which("uv")  # use 'uv pip' if available, speeds things up a lot and is the default in raspOVOS

    def __init__(self, bus, config=None):
        self.config = config or Configuration().get("skills", {}).get("installer", {})
        self.bus = bus
        self.bus.on("ovos.skills.install", self.handle_install_skill)
        self.bus.on("ovos.skills.uninstall", self.handle_uninstall_skill)
        self.bus.on("ovos.pip.install", self.handle_install_python)
        self.bus.on("ovos.pip.uninstall", self.handle_uninstall_python)

    def shutdown(self) -> None:
        """Unregister all message bus event handlers."""
        self.bus.remove("ovos.skills.install", self.handle_install_skill)
        self.bus.remove("ovos.skills.uninstall", self.handle_uninstall_skill)
        self.bus.remove("ovos.pip.install", self.handle_install_python)
        self.bus.remove("ovos.pip.uninstall", self.handle_uninstall_python)

    def play_error_sound(self) -> None:
        """Emit a message to play the configured error sound."""
        snd = self.config.get("sounds", {}).get("pip_error", "snd/error.mp3")
        self.bus.emit(Message("mycroft.audio.play_sound", {"uri": snd}))

    def play_success_sound(self) -> None:
        """Emit a message to play the configured success sound."""
        snd = self.config.get("sounds", {}).get("pip_success", "snd/acknowledge.mp3")
        self.bus.emit(Message("mycroft.audio.play_sound", {"uri": snd}))

    @staticmethod
    def validate_constraints(constraints: str) -> bool:
        """Validate a constraints file path or URL.

        Args:
            constraints (str): Local file path or HTTP URL to a pip constraints file.

        Returns:
            bool: True if the constraints file is accessible, False otherwise.
        """
        if constraints.startswith('http'):
            LOG.debug(f"Constraints url: {constraints}")
            try:
                response = requests.head(constraints)
                if response.status_code != 200:
                    LOG.error(f'Remote constraints file not accessible: {response.status_code}')
                    return False
                return True
            except Exception as e:
                LOG.error(f'Error accessing remote constraints: {str(e)}')
                return False

        # Use constraints to limit the installed versions
        if not exists(constraints):
            LOG.error('Couldn\'t find the constraints file')
            return False

        return True

    def pip_install(self, packages: list,
                    constraints: Optional[str] = None,
                    print_logs: bool = True) -> bool:
        """Install Python packages via pip or uv.

        Args:
            packages (list): List of package specifiers to install.
            constraints (str): Optional constraints file path or URL.
            print_logs (bool): Whether to print pip output to stdout.

        Returns:
            bool: True if all packages were installed successfully, False otherwise.
        """
        if not len(packages):
            LOG.error("no package list provided to install")
            self.play_error_sound()
            return False

        # can be set in mycroft.conf to change to testing/alpha channels
        constraints = constraints or self.config.get("constraints", SkillsStore.DEFAULT_CONSTRAINTS)

        if not self.validate_constraints(constraints):
            self.play_error_sound()
            return False

        if self.UV is not None:
            pip_args = [self.UV, 'pip', 'install']
        else:
            pip_args = [sys.executable, '-m', 'pip', 'install']
        if constraints:
            pip_args += ['-c', constraints]
        if self.config.get("break_system_packages", False):
            pip_args += ["--break-system-packages"]
        if self.config.get("allow_alphas", False):
            pip_args += ["--pre"]

        with SkillsStore.PIP_LOCK:
            """
            Iterate over the individual Python packages and
            install them one by one to enforce the order specified
            in the manifest.
            """
            for dependent_python_package in packages:
                LOG.info("(pip) Installing " + dependent_python_package)
                pip_command = pip_args + [dependent_python_package]
                LOG.debug(" ".join(pip_command))
                if print_logs:
                    proc = Popen(pip_command)
                else:
                    proc = Popen(pip_command, stdout=PIPE, stderr=PIPE)
                pip_code = proc.wait()
                if pip_code != 0:
                    stderr = proc.stderr
                    if stderr:
                        stderr = stderr.read().decode()
                    self.play_error_sound()
                    raise RuntimeError(stderr)

        reload(ovos_plugin_manager)  # force core to pick new entry points
        self.play_success_sound()
        return True

    def pip_uninstall(self, packages: list,
                      constraints: Optional[str] = None,
                      print_logs: bool = True) -> bool:
        """Uninstall Python packages via pip or uv.

        Protected packages (listed in the constraints file) cannot be removed.

        Args:
            packages (list): List of package names to uninstall.
            constraints (str): Optional constraints file path or URL used to identify protected packages.
            print_logs (bool): Whether to print pip output to stdout.

        Returns:
            bool: True if all packages were uninstalled successfully, False otherwise.
        """
        if not len(packages):
            LOG.error("no package list provided to uninstall")
            self.play_error_sound()
            return False

        # can be set in mycroft.conf to change to testing/alpha channels
        constraints = constraints or self.config.get("constraints", SkillsStore.DEFAULT_CONSTRAINTS)

        if not self.validate_constraints(constraints):
            self.play_error_sound()
            return False

        # get protected packages that can't be uninstalled
        # by default cant uninstall any official ovos package via this bus api
        if constraints.startswith("http"):
            cpkgs = requests.get(constraints).text.split("\n")
        elif exists(constraints):
            with open(constraints) as f:
                cpkgs = f.read().split("\n")
        else:
            cpkgs = ["ovos-core", "ovos-utils", "ovos-plugin-manager",
                     "ovos-config", "ovos-bus-client", "ovos-workshop"]

        # remove version pinning and normalize _ to - (pip accepts both)
        cpkgs = [p.split("~")[0].split("<")[0].split(">")[0].split("=")[0].replace("_", "-")
                 for p in cpkgs]

        if any(p in cpkgs for p in packages):
            LOG.error(f'tried to uninstall a protected package: {cpkgs}')
            self.play_error_sound()
            return False

        if self.UV is not None:
            pip_args = [self.UV, 'pip', 'uninstall']
        else:
            pip_args = [sys.executable, '-m', 'pip', 'uninstall', '-y']
        if self.config.get("break_system_packages", False):
            pip_args += ["--break-system-packages"]

        with SkillsStore.PIP_LOCK:
            """
            Iterate over the individual Python packages and
            install them one by one to enforce the order specified
            in the manifest.
            """
            for dependent_python_package in packages:
                LOG.info("(pip) Uninstalling " + dependent_python_package)
                pip_command = pip_args + [dependent_python_package]
                LOG.debug(" ".join(pip_command))
                if print_logs:
                    proc = Popen(pip_command)
                else:
                    proc = Popen(pip_command, stdout=PIPE, stderr=PIPE)
                pip_code = proc.wait()
                if pip_code != 0:
                    stderr = proc.stderr.read().decode()
                    self.play_error_sound()
                    raise RuntimeError(stderr)

        reload(ovos_plugin_manager)  # force core to pick new entry points
        self.play_success_sound()
        return True

    @staticmethod
    def validate_skill(url: str) -> bool:
        """Validate that a skill URL is an installable GitHub skill.

        Performs lightweight GitHub API validation (no auth required for public
        repos).  The checks are:

        1. URL must start with ``https://github.com/``.
        2. The repository must exist (HTTP 200 from the GitHub contents API).
        3. The repo must contain ``pyproject.toml`` or ``setup.cfg`` — a bare
           ``setup.py``-only repo is rejected as it indicates a legacy skill.
        4. ``pyproject.toml`` / ``setup.cfg`` must *not* reference ``MycroftSkill``
           or ``CommonPlaySkill`` — those class names indicate an incompatible
           legacy skill.

        The GitHub API call uses a 3-second timeout; if GitHub is unreachable
        the method falls back to ``True`` so that a transient network error does
        not block legitimate installs.

        Args:
            url (str): GitHub repository URL of the skill
                (e.g. ``https://github.com/OpenVoiceOS/ovos-skill-hello-world``).

        Returns:
            bool: True if the URL points to a valid, OVOS-compatible GitHub skill;
                  False if the URL is invalid or the repo fails any check.
        """
        if not url.startswith("https://github.com/"):
            return False

        # parse owner/repo from URL (strip trailing .git or extra path segments)
        path = url[len("https://github.com/"):].rstrip("/")
        parts = path.split("/")
        if len(parts) < 2:
            LOG.warning(f"validate_skill: cannot parse owner/repo from '{url}'")
            return False
        owner, repo = parts[0], parts[1].removesuffix(".git")

        api_base = f"https://api.github.com/repos/{owner}/{repo}/contents/"
        try:
            response = requests.get(api_base, timeout=3,
                                    headers={"Accept": "application/vnd.github+json"})
        except Exception as exc:
            LOG.warning(f"validate_skill: GitHub unreachable, skipping deep check — {exc}")
            return True  # fail open: transient network errors should not block installs

        if response.status_code == 404:
            LOG.warning(f"validate_skill: repo not found — {owner}/{repo}")
            return False
        if not response.ok:
            LOG.warning(f"validate_skill: GitHub API returned {response.status_code} for {url}, skipping deep check")
            return True  # fail open on unexpected API errors

        file_names = {entry["name"] for entry in response.json()
                      if isinstance(entry, dict)}

        # reject bare setup.py-only repos (legacy Mycroft packaging)
        if "setup.py" in file_names and "pyproject.toml" not in file_names and "setup.cfg" not in file_names:
            LOG.warning(f"validate_skill: '{owner}/{repo}' uses only setup.py — legacy packaging, rejecting")
            return False

        # fetch the modern packaging manifest to scan for incompatible base classes
        for manifest in ("pyproject.toml", "setup.cfg"):
            if manifest not in file_names:
                continue
            manifest_url = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{manifest}"
            try:
                manifest_resp = requests.get(manifest_url, timeout=3)
            except Exception as exc:
                LOG.warning(f"validate_skill: could not fetch {manifest} — {exc}")
                break
            if not manifest_resp.ok:
                break
            content = manifest_resp.text
            for legacy_class in ("MycroftSkill", "CommonPlaySkill"):
                if legacy_class in content:
                    LOG.warning(
                        f"validate_skill: '{owner}/{repo}' references {legacy_class} — "
                        f"incompatible legacy skill, rejecting"
                    )
                    return False
            break  # only need to check one manifest

        return True

    def handle_install_skill(self, message: Message) -> None:
        """Handle a request to install a skill from a GitHub URL."""
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.skills.install.failed",
                                        {"error": InstallError.DISABLED.value}))
            return

        url = message.data["url"]
        if self.validate_skill(url):
            success = self.pip_install([f"git+{url}"])
            if success:
                self.bus.emit(message.reply("ovos.skills.install.complete"))
            else:
                self.bus.emit(message.reply("ovos.skills.install.failed",
                                            {"error": InstallError.PIP_ERROR.value}))
        else:
            LOG.error("invalid skill url, does not appear to be a github skill")
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.skills.install.failed",
                                        {"error": InstallError.BAD_URL.value}))

    def handle_uninstall_skill(self, message: Message) -> None:
        """Handle a request to uninstall a skill.

        Args:
            message (Message): Bus message with data containing 'skill' (skill_id or package name).
        """
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.skills.uninstall.failed",
                                        {"error": InstallError.DISABLED.value}))
            return

        skill = message.data.get("skill")
        if not skill:
            LOG.error("no skill specified for uninstall")
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.skills.uninstall.failed",
                                        {"error": InstallError.NO_PKGS.value}))
            return

        # Treat skill_id as a package name (e.g., 'skill-name.author' -> 'skill-name-author')
        # or accept directly as package name
        pkg_name = skill.replace(".", "-") if "." in skill else skill

        if self.pip_uninstall([pkg_name]):
            LOG.info(f"Successfully uninstalled skill: {skill}")
            self.bus.emit(message.reply("ovos.skills.uninstall.complete"))
        else:
            LOG.error(f"Failed to uninstall skill: {skill}")
            self.bus.emit(message.reply("ovos.skills.uninstall.failed",
                                        {"error": InstallError.PIP_ERROR.value}))

    def handle_install_python(self, message: Message) -> None:
        """Handle a request to install arbitrary Python packages via pip."""
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.pip.install.failed",
                                        {"error": InstallError.DISABLED.value}))
            return
        pkgs = message.data.get("packages")
        if pkgs:
            if self.pip_install(pkgs):
                self.bus.emit(message.reply("ovos.pip.install.complete"))
            else:
                self.bus.emit(message.reply("ovos.pip.install.failed",
                                            {"error": InstallError.PIP_ERROR.value}))
        else:
            self.bus.emit(message.reply("ovos.pip.install.failed",
                                        {"error": InstallError.NO_PKGS.value}))

    def handle_uninstall_python(self, message: Message) -> None:
        """Handle a request to uninstall Python packages via pip."""
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.pip.uninstall.failed",
                                        {"error": InstallError.DISABLED.value}))
            return
        pkgs = message.data.get("packages")
        if pkgs:
            if self.pip_uninstall(pkgs):
                self.bus.emit(message.reply("ovos.pip.uninstall.complete"))
            else:
                self.bus.emit(message.reply("ovos.pip.uninstall.failed",
                                            {"error": InstallError.PIP_ERROR.value}))
        else:
            self.bus.emit(message.reply("ovos.pip.uninstall.failed",
                                        {"error": InstallError.NO_PKGS.value}))


def launch_standalone():
    """Launch SkillsStore as a standalone service on the messagebus.

    Warns the user if running in a container (Docker/Podman) where pip may
    fail due to filesystem or permission issues.
    """
    from ovos_bus_client import MessageBusClient
    from ovos_utils import wait_for_exit_signal
    from ovos_utils.log import init_service_logger

    # Warn if running in a container
    if exists("/.dockerenv") or exists("/run/.containerenv"):
        LOG.warning(
            "⚠️  SkillsStore is running inside a container (Docker/Podman). "
            "Pip install/uninstall may fail if the container filesystem is read-only. "
            "Mount a writable volume or use 'pip' with appropriate flags."
        )

    LOG.info("Launching SkillsStore in standalone mode")
    init_service_logger("skill-installer")

    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait()

    store = SkillsStore(bus)

    wait_for_exit_signal()

    store.shutdown()

    LOG.info('SkillsStore shutdown complete!')


if __name__ == "__main__":
    launch_standalone()
