import sys
from os.path import join, exists
from subprocess import Popen, PIPE
from tempfile import gettempdir
from typing import Optional

from combo_lock import ComboLock
from ovos_config.config import Configuration

from ovos_bus_client import Message
from ovos_utils.log import LOG


class SkillsStore:
    # default constraints to use if none are given
    DEFAULT_CONSTRAINTS = '/etc/mycroft/constraints.txt'
    PIP_LOCK = ComboLock(join(gettempdir(), "ovos_pip.lock"))

    def __init__(self, bus, config=None):
        self.config = config or Configuration()["skills"]
        self.bus = bus
        self.bus.on("ovos.skills.install", self.handle_install_skill)

    def shutdown(self):
        pass

    @staticmethod
    def pip_install(packages: list, constraints: Optional[str] = None, print_logs: bool = False):
        if not len(packages):
            return False
        # Use constraints to limit the installed versions
        if constraints and not exists(constraints):
            LOG.error('Couldn\'t find the constraints file')
            return False
        elif exists(SkillsStore.DEFAULT_CONSTRAINTS):
            constraints = SkillsStore.DEFAULT_CONSTRAINTS

        pip_args = [sys.executable, '-m', 'pip', 'install']
        if constraints:
            pip_args += ['-c', constraints]

        with SkillsStore.PIP_LOCK:
            """
            Iterate over the individual Python packages and
            install them one by one to enforce the order specified
            in the manifest.
            """
            for dependent_python_package in packages:
                LOG.info("(pip) Installing " + dependent_python_package)
                pip_command = pip_args + [dependent_python_package]
                if print_logs:
                    proc = Popen(pip_command)
                else:
                    proc = Popen(pip_command, stdout=PIPE, stderr=PIPE)
                pip_code = proc.wait()
                if pip_code != 0:
                    stderr = proc.stderr.read().decode()
                    raise RuntimeError(stderr)

        return True

    def validate_skill(self, url):
        if not url.startswith("https://github.com/"):
            return False
        # TODO - check if setup.py
        # TODO - check if not using MycroftSkill class
        # TODO - check if not mycroft CommonPlay
        return True

    def handle_install_skill(self, message: Message):
        url = message.data["url"]
        if self.validate_skill(url):
            success = self.pip_install([f"git+{url}"])
            if success:
                self.bus.emit(message.reply("ovos.skills.install.complete"))
            else:
                self.bus.emit(message.reply("ovos.skills.install.failed", {"error": "pip install failed"}))
        else:
            self.bus.emit(message.reply("ovos.skills.install.failed", {"error": "not a github url"}))
