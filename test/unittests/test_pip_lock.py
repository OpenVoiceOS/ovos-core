"""The pip lock holds across processes and threads, and needs no combo-lock."""
import os
import re
import subprocess
import sys
import threading
import time
from importlib.metadata import requires
from pathlib import Path
from tempfile import gettempdir

from ovos_core.skill_installer import SkillsStore

HOLD_SECONDS = 1.5

# File name that combo-lock 0.3.1 NamedLock("ovos_pip.lock") uses.
COMBO_LOCK_PATH = Path(gettempdir(), "combo_locks", "b3Zvc19waXAubG9jaw==.lock")

HOLDER = f"""
import time
from ovos_core.skill_installer import SkillsStore
with SkillsStore.PIP_LOCK:
    print("held", flush=True)
    time.sleep({HOLD_SECONDS})
"""


def requirement_names(dist: str) -> set:
    return {re.split(r"[\s;<>=!~\[]", req, maxsplit=1)[0].lower().replace("_", "-")
            for req in requires(dist) or []}


def test_metadata_requires_filelock_not_combo_lock():
    names = requirement_names("ovos-core")
    assert "combo-lock" not in names
    assert "filelock" in names


def test_lock_file_is_the_combo_lock_path():
    assert Path(SkillsStore.PIP_LOCK.lock_file) == COMBO_LOCK_PATH
    with SkillsStore.PIP_LOCK:
        assert os.stat(COMBO_LOCK_PATH).st_mode & 0o777 == 0o666


def test_other_process_waits_for_release():
    holder = subprocess.Popen([sys.executable, "-c", HOLDER],
                              stdout=subprocess.PIPE, text=True)
    try:
        # The package logs to stdout, so skip lines until the marker.
        assert "held" in (line.strip() for line in holder.stdout)
        start = time.monotonic()
        with SkillsStore.PIP_LOCK:
            waited = time.monotonic() - start
    finally:
        holder.wait(timeout=60)
    assert holder.returncode == 0
    assert waited > HOLD_SECONDS / 2


def test_other_thread_waits_for_release():
    held = threading.Event()

    def hold():
        with SkillsStore.PIP_LOCK:
            held.set()
            time.sleep(HOLD_SECONDS)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(timeout=10)
    start = time.monotonic()
    with SkillsStore.PIP_LOCK:
        waited = time.monotonic() - start
    holder.join()
    assert waited > HOLD_SECONDS / 2
