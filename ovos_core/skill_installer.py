import enum
import re
import shutil
import sys
from importlib import reload
from os.path import exists
from subprocess import Popen, PIPE, STDOUT
from typing import Optional

import requests
from combo_lock import NamedLock
from packaging.utils import canonicalize_name
from ovos_bus_client import Message
from ovos_config.config import Configuration
from ovos_utils.log import LOG

import ovos_plugin_manager


class InstallError(str, enum.Enum):
    DISABLED = "pip disabled in mycroft.conf"
    PIP_ERROR = "error in pip subprocess"
    BAD_URL = "skill url validation failed"
    NO_PKGS = "no packages to install"


#: how much of the installer's output a ``.failed`` reply carries in ``detail``
FAILURE_DETAIL_CHARS = 2000



def _strip_requirement_comment(line: str) -> str:
    """A requirements line without its comment, by pip's rule.

    ``#`` starts a comment at the beginning of a line or after whitespace;
    anywhere else it is part of a URL (``...#egg=name``, ``...#sha256=...``).
    """
    return re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()

class SkillsStore:
    # default constraints to use if none are given
    DEFAULT_CONSTRAINTS = 'https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/refs/heads/main/constraints-stable.txt'
    PIP_LOCK = NamedLock("ovos_pip.lock")
    UV = shutil.which("uv")  # use 'uv pip' if available, speeds things up a lot and is the default in raspOVOS

    #: OVOS-INSTALL-1 §2.3: the name a request addresses this service by,
    #: in ``data.service_name``. The skills service owns skills, solvers,
    #: personas, pipeline stages and utterance transformers.
    SERVICE_NAME = "ovos_core"

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
    def failure_detail(output) -> str:
        """The tail of an installer run's output, sized for a bus reply.

        Args:
            output: The captured output, or the ``RuntimeError`` carrying it.

        Returns:
            str: At most ``FAILURE_DETAIL_CHARS`` characters, taken from the end,
                since that is where pip and uv explain why a run failed.
        """
        return str(output or "")[-FAILURE_DETAIL_CHARS:]

    def _reply_failed(self, message: Message, topic: str, error: str, detail: str = "") -> None:
        """Reply to a request with a ``.failed`` message.

        Args:
            message (Message): The request being answered.
            topic (str): The ``.failed`` topic.
            error (str): The ``InstallError`` value (or exception text) naming the failure.
            detail (str): The installer's output tail, empty when pip did not run.
        """
        self.bus.emit(message.reply(topic, {"error": error, "detail": detail}))

    @staticmethod
    def _run_pip(pip_command: list, print_logs: bool) -> str:
        """Run one pip/uv command and return what it printed.

        stdout and stderr are captured as a single stream: uv writes everything
        to stderr, pip splits progress and errors across the two, and the last
        lines of the merged stream are the ones that say why a run failed. With
        ``print_logs`` every line is also echoed through ``LOG`` as it arrives.

        Args:
            pip_command (list): The full command line.
            print_logs (bool): Whether to echo the output to the log.

        Returns:
            str: The captured output.

        Raises:
            RuntimeError: On a non-zero exit, carrying the captured output.
        """
        lines = []
        with Popen(pip_command, stdout=PIPE, stderr=STDOUT, text=True, errors="replace") as proc:
            for line in proc.stdout or []:
                line = line.rstrip("\n")
                lines.append(line)
                if print_logs:
                    LOG.info(f"(pip) {line}")
        output = "\n".join(lines)
        if proc.returncode != 0:
            raise RuntimeError(output)
        return output

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
            print_logs (bool): Whether to echo pip output to the log.

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
        if self.config.get("upgrade", False):
            pip_args += ["--upgrade"]

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
                try:
                    self._run_pip(pip_command, print_logs)
                except RuntimeError:
                    self.play_error_sound()
                    raise

        reload(ovos_plugin_manager)  # force core to pick new entry points
        self.play_success_sound()
        return True

    @staticmethod
    def _includes_another_file(line: str) -> bool:
        """Whether a constraints line pulls in a second file.

        ``-r``/``--requirement`` and ``-c``/``--constraint`` make pip apply
        pins this file does not list, so a protected set built from this text
        alone is not the set pip would enforce.

        Args:
            line: one raw line from the constraints file.

        Returns:
            True when the line is an include.
        """
        line = _strip_requirement_comment(line)
        return bool(re.match(r"^(-r|-c|--requirement|--constraint)(\s|=|$)", line))

    @staticmethod
    def _constrained_name(line: str) -> Optional[str]:
        """The distribution a constraints line names, canonicalized, or None.

        Handles what a requirements/constraints file actually contains: a
        comment, a blank line, a pip option (``-r``, ``--index-url``), an
        inline comment after a requirement, extras, and an environment
        marker. Names are canonicalized per PEP 503, so "ovos_core",
        "OVOS-Core" and "ovos.core" all compare equal to "ovos-core" the way
        pip and PyPI identify distributions.

        Args:
            line: one raw line from the constraints file.

        Returns:
            The canonical distribution name, or None when the line names none.
        """
        # pip's rule: ``#`` begins a comment at the start of a line or after
        # whitespace. A ``#`` glued to a URL is a fragment and stays. Reading
        # ``#egg=`` before applying this let a comment rename the pin --
        # ``ovos-core==1.0  # see #egg=other`` protected "other" and left
        # ovos-core removable.
        line = _strip_requirement_comment(line)
        if not line:
            return None
        if line.startswith("-"):
            # A bare option names no distribution. ``-e <path|url>`` does.
            editable = re.match(r"^(-e|--editable)(\s+|=)(.+)$", line)
            if not editable:
                return None
            line = editable.group(3).strip()

        line = line.split(";", 1)[0].strip()  # environment marker

        # PEP 508 direct reference: pip takes the name before ``@``, whatever
        # the URL after it says, so a fragment there must not override it.
        direct = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*@", line)
        if direct:
            return canonicalize_name(direct.group(1))

        # A wheel names its distribution in the filename (PEP 427:
        # ``{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl``)
        # whether it arrives as a URL or a local path.
        wheel = re.search(r"([^/\\]+)\.whl(?:[?#].*)?$", line)
        if wheel:
            return canonicalize_name(wheel.group(1).split("-", 1)[0])

        # An sdist archive names it the same way.
        sdist = re.search(r"([^/\\]+)\.(?:tar\.gz|zip)(?:[?#].*)?$", line)
        if sdist:
            stem = sdist.group(1)
            return canonicalize_name(re.split(r"-\d", stem, maxsplit=1)[0])

        # Only now, and only on a URL or VCS target, does ``#egg=`` name the
        # distribution: it is the one place that does for a VCS pin.
        if re.match(r"^(?:[a-z]+\+)?[a-z][a-z0-9.+-]*://|^file:", line, re.I):
            egg = re.search(r"#egg=([A-Za-z0-9._-]+)", line)
            return canonicalize_name(egg.group(1)) if egg else None

        name = re.split(r"[\[<>=!~\s]", line, maxsplit=1)[0].strip()
        if not name:
            return None
        # Anything still carrying a separator is a path this parser did not
        # recognise. Returning it would be a "name" matching no package, which
        # is the fail-open the caller refuses on.
        if any(sep in name for sep in ("/", "\\", ":")):
            return None
        return canonicalize_name(name)

    def pip_uninstall(self, packages: list,
                      constraints: Optional[str] = None,
                      print_logs: bool = True) -> bool:
        """Uninstall Python packages via pip or uv.

        Protected packages (listed in the constraints file) cannot be removed.

        Args:
            packages (list): List of package names to uninstall.
            constraints (str): Optional constraints file path or URL used to identify protected packages.
            print_logs (bool): Whether to echo pip output to the log.

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

        # The name used to be taken by splitting on the version operators
        # alone, which left everything else on the line attached to it. That
        # under-protects, which is the dangerous direction: "  ovos-core==1.0"
        # yielded "  ovos-core", "ovos-core[extra]==1.0" yielded
        # "ovos-core[extra]", and a line carrying an environment marker was cut
        # at the marker's own "<". None of those equal "ovos-core", so a pin
        # written any of those perfectly ordinary ways protected nothing and
        # the package it named could be uninstalled over the bus.
        #
        # Reading the line properly also keeps comments, blank lines and pip
        # options out of the set, so the refusal below can name the package it
        # refused instead of printing the whole file.
        # Each requested name is forwarded to pip/uv on its own command line,
        # so an entry that is really an option ("-r evil.txt", "--index-url
        # ...") is read as one. Canonicalizing it first would not help: it
        # matches no protected name, so the guard below waves it through.
        # Refuse before anything else looks at it, for pip and uv alike.
        option_like = [p for p in packages if str(p).strip().startswith("-")]
        if option_like:
            LOG.error(f'refusing option-like package names: {option_like}')
            self.play_error_sound()
            return False

        # An include pulls in pins this file does not list, so the protected
        # set built from this text alone is not the set pip would apply.
        # Refusing is the only safe answer: proceeding would under-protect,
        # which is the failure this guard exists to prevent.
        if any(self._includes_another_file(p) for p in cpkgs):
            LOG.error('constraints file includes another file; the protected '
                      'set cannot be known to be complete, refusing')
            self.play_error_sound()
            return False

        # A line that carries a requirement but yields no name leaves the
        # protected set smaller than the set pip would apply -- the same
        # under-protection the include guard above refuses for. A wheel URL, a
        # local wheel path and an ``#egg=`` VCS pin each name a distribution
        # and are parsed; what is left here is a form this parser cannot read,
        # and guessing is exactly the fail-open this guard exists to prevent.
        unreadable = [
            line for line in cpkgs
            if _strip_requirement_comment(line)
            and self._constrained_name(line) is None
            and not _strip_requirement_comment(line).startswith("-")
        ]
        if unreadable:
            LOG.error('constraints file has requirement lines whose '
                      f'distribution cannot be determined: {unreadable}; '
                      'the protected set cannot be known to be complete, '
                      'refusing')
            self.play_error_sound()
            return False

        protected = {name for name in (self._constrained_name(p) for p in cpkgs) if name}

        norm_packages = [canonicalize_name(p) for p in packages]

        refused = sorted({p for p in norm_packages if p in protected})
        if refused:
            LOG.error(f'tried to uninstall protected packages: {refused}')
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
                try:
                    self._run_pip(pip_command, print_logs)
                except RuntimeError:
                    self.play_error_sound()
                    raise

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
        3. The repo must contain ``pyproject.toml`` or ``setup.cfg`` or ``setup.py``
           — a bare repo is rejected as it indicates a legacy skill.
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
        if "setup.py" not in file_names and "pyproject.toml" not in file_names and "setup.cfg" not in file_names:
            LOG.warning(f"validate_skill: '{owner}/{repo}' - legacy packaging, rejecting")
            return False

        return True

    def handle_install_skill(self, message: Message) -> None:
        """Handle a request to install a skill from a GitHub URL."""
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self._reply_failed(message, "ovos.skills.install.failed", InstallError.DISABLED.value)
            return

        url = message.data["url"]
        if self.validate_skill(url):
            detail = ""
            try:
                success = self.pip_install([f"git+{url}"])
            except RuntimeError as e:
                LOG.error(f"pip failed: {e}")
                success = False
                detail = self.failure_detail(e)
            if success:
                self.bus.emit(message.reply("ovos.skills.install.complete"))
            else:
                self._reply_failed(message, "ovos.skills.install.failed", InstallError.PIP_ERROR.value, detail)
        else:
            LOG.error("invalid skill url, does not appear to be a github skill")
            self.play_error_sound()
            self._reply_failed(message, "ovos.skills.install.failed", InstallError.BAD_URL.value)

    def handle_uninstall_skill(self, message: Message) -> None:
        """Handle a request to uninstall a skill.

        Args:
            message (Message): Bus message with data containing 'skill' (skill_id or package name).
        """
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self._reply_failed(message, "ovos.skills.uninstall.failed", InstallError.DISABLED.value)
            return

        skill = message.data.get("skill")
        if not skill:
            LOG.error("no skill specified for uninstall")
            self.play_error_sound()
            self._reply_failed(message, "ovos.skills.uninstall.failed", InstallError.NO_PKGS.value)
            return

        # Treat skill_id as a package name (e.g., 'skill-name.author' -> 'skill-name-author')
        # or accept directly as package name
        pkg_name = skill.replace(".", "-") if "." in skill else skill

        try:
            if self.pip_uninstall([pkg_name]):
                LOG.info(f"Successfully uninstalled skill: {skill}")
                self.bus.emit(message.reply("ovos.skills.uninstall.complete"))
            else:
                LOG.error(f"Failed to uninstall skill: {skill}")
                self._reply_failed(message, "ovos.skills.uninstall.failed", InstallError.PIP_ERROR.value)
        except Exception as e:
            LOG.exception(f"Error uninstalling skill {skill}: {e}")
            self._reply_failed(message, "ovos.skills.uninstall.failed", str(e), self.failure_detail(e))

    def _addressed_to_us(self, message: Message) -> bool:
        """Whether this service should act on a pip request.

        OVOS-INSTALL-1 §2.2: ``data.service_name`` names the one service a
        request is for. Absent, every installer acts. Naming another service,
        this one installs nothing and answers nothing, because a decline from
        every other installer would bury the real answer in a burst the
        client cannot pick it out of.

        The comparison is exact: a service name is an identifier, not a
        pattern.
        """
        target = message.data.get("service_name")
        if target is None or target == self.SERVICE_NAME:
            return True
        LOG.debug(f"{message.msg_type} is addressed to '{target}', "
                  f"not '{self.SERVICE_NAME}'; ignoring")
        return False

    def handle_install_python(self, message: Message) -> None:
        """Handle a request to install arbitrary Python packages via pip."""
        if not self._addressed_to_us(message):
            return
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self._reply_failed(message, "ovos.pip.install.failed", InstallError.DISABLED.value)
            return
        pkgs = message.data.get("packages")
        if pkgs:
            detail = ""
            try:
                success = self.pip_install(pkgs)
            except RuntimeError as e:
                LOG.error(f"pip failed: {e}")
                success = False
                detail = self.failure_detail(e)
            if success:
                self.bus.emit(message.reply("ovos.pip.install.complete"))
            else:
                self._reply_failed(message, "ovos.pip.install.failed", InstallError.PIP_ERROR.value, detail)
        else:
            self._reply_failed(message, "ovos.pip.install.failed", InstallError.NO_PKGS.value)

    def handle_uninstall_python(self, message: Message) -> None:
        """Handle a request to uninstall Python packages via pip."""
        if not self._addressed_to_us(message):
            return
        if not self.config.get("allow_pip"):
            LOG.error(InstallError.DISABLED.value)
            self.play_error_sound()
            self._reply_failed(message, "ovos.pip.uninstall.failed", InstallError.DISABLED.value)
            return
        pkgs = message.data.get("packages")
        if pkgs:
            detail = ""
            try:
                success = self.pip_uninstall(pkgs)
            except RuntimeError as e:
                LOG.error(f"pip failed: {e}")
                success = False
                detail = self.failure_detail(e)
            if success:
                self.bus.emit(message.reply("ovos.pip.uninstall.complete"))
            else:
                self._reply_failed(message, "ovos.pip.uninstall.failed", InstallError.PIP_ERROR.value, detail)
        else:
            self._reply_failed(message, "ovos.pip.uninstall.failed", InstallError.NO_PKGS.value)


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
