import enum
import sys
from importlib import reload
from os.path import exists
from subprocess import Popen, PIPE
from typing import Optional

from combo_lock import NamedLock
from ovos_config.config import Configuration

import ovos_plugin_manager
from ovos_bus_client import Message
from ovos_utils.log import LOG


class InstallError(str, enum.Enum):
    DISABLED = "pip disabled in mycroft.conf"
    PIP_ERROR = "error in pip subprocess"
    BAD_URL = "skill url validation failed"
    NO_PKGS = "no packages to install"


class SkillsStore:
    # default constraints to use if none are given
    DEFAULT_CONSTRAINTS = '/etc/mycroft/constraints.txt'  # TODO XDG paths, keep backwards compat for now with msm/osm
    PIP_LOCK = NamedLock("ovos_pip.lock")

    def __init__(self, bus, config=None):
        self.config = config or Configuration().get("skills", {}).get("installer", {})
        self.bus = bus
        self.bus.on("ovos.skills.install", self.handle_install_skill)
        self.bus.on("ovos.skills.uninstall", self.handle_uninstall_skill)
        self.bus.on("ovos.pip.install", self.handle_install_python)
        self.bus.on("ovos.pip.uninstall", self.handle_uninstall_python)

    def shutdown(self):
        pass

    def play_error_sound(self):
        snd = self.config.get("sounds", {}).get("pip_error", "snd/error.mp3")
        self.bus.emit(Message("mycroft.audio.play_sound", {"uri": snd}))

    def play_success_sound(self):
        snd = self.config.get("sounds", {}).get("pip_success", "snd/acknowledge.mp3")
        self.bus.emit(Message("mycroft.audio.play_sound", {"uri": snd}))

    def pip_install(self, packages: list,
                    constraints: Optional[str] = None,
                    print_logs: bool = True):
        if not len(packages):
            LOG.error("no package list provided to install")
            self.play_error_sound()
            return False
        # Use constraints to limit the installed versions
        if constraints and not exists(constraints):
            LOG.error('Couldn\'t find the constraints file')
            self.play_error_sound()
            return False
        elif exists(SkillsStore.DEFAULT_CONSTRAINTS):
            constraints = SkillsStore.DEFAULT_CONSTRAINTS

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
                      print_logs: bool = True):
        if not len(packages):
            LOG.error("no package list provided to uninstall")
            self.play_error_sound()
            return False

        # Use constraints to limit package removal
        if constraints and not exists(constraints):
            LOG.error('Couldn\'t find the constraints file')
            self.play_error_sound()
            return False
        elif exists(SkillsStore.DEFAULT_CONSTRAINTS):
            constraints = SkillsStore.DEFAULT_CONSTRAINTS

        if constraints:
            with open(constraints) as f:
                # remove version pinning and normalize _ to - (pip accepts both)
                cpkgs = [p.split("~")[0].split("<")[0].split(">")[0].split("=")[0].replace("_", "-")
                         for p in f.read().split("\n") if p.strip()]
        else:
            cpkgs = ["ovos-core", "ovos-utils", "ovos-plugin-manager",
                     "ovos-config", "ovos-bus-client", "ovos-workshop"]

        # normalize _ to - (pip accepts both)
        if any(p.replace("_", "-") in cpkgs for p in packages):
            LOG.error(f'tried to uninstall a protected package: {cpkgs}')
            self.play_error_sound()
            return False

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

    def validate_skill(self, url):
        if not url.startswith("https://github.com/"):
            return False
        # TODO - check if setup.py
        # TODO - check if not using MycroftSkill class
        # TODO - check if not mycroft CommonPlay
        return True

    def handle_install_skill(self, message: Message):
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

    def handle_uninstall_skill(self, message: Message):
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self.bus.emit(message.reply("ovos.skills.uninstall.failed",
                                        {"error": InstallError.DISABLED.value}))
            return
        # TODO
        LOG.error("pip uninstall not yet implemented")
        self.play_error_sound()
        self.bus.emit(message.reply("ovos.skills.uninstall.failed",
                                    {"error": "not implemented"}))

    def handle_install_python(self, message: Message):
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

    def handle_uninstall_python(self, message: Message):
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
