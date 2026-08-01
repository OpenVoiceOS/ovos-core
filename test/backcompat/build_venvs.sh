#!/usr/bin/env bash
# Build the four venvs the mixed-version back-compat matrix runs against.
#
# Two venvs are alive per combo: one holds the skill's packages, one holds the
# core's. They talk over a real websocket, which is the only way one test run
# can observe two different package sets.
#
# Usage:  test/backcompat/build_venvs.sh <target-dir> [path-to-core-checkout]
#
# Pins, and why each one is where it is:
#
#   skill_old  ovos-workshop==9.3.1a2
#              The newest release that binds the handler to the suffixed
#              `<skill_id>:<file>.intent` topic ONLY. 9.3.2a1 added the
#              canonical binding alongside it (ovos-workshop#497), which hides
#              the breakage, so the pin must stay below that line.
#              ovos-bus-client is deliberately NOT pinned: a real frozen
#              container resolves the workshop floor and gets a current client,
#              and the repair in ovos-bus-client#271 depends on exactly that.
#
#   skill_new  ovos-workshop @ dev
#              Binds both spellings today. ovos-workshop#500 makes it
#              canonical-only, which is what will turn the new-skill/old-core
#              cell red.
#
#   core_old   ovos-core==2.5.5a2 + ovos-padatious==2.0.0a1
#              The newest padatious release BEFORE registration-time
#              canonicalization (`_dealias_intent_name`, added in 2.0.1a1), so
#              this side dispatches whatever the skill registered. ovos-core is
#              pinned to its contemporary release; core itself forwards
#              `match.match_type` verbatim, so the pipeline plugin is the part
#              that decides the spelling.
#
#   core_new   this checkout + ovos-padatious>=2.0.1a2
#              Folds at registration, so it dispatches the canonical topic.
set -euo pipefail

TARGET="${1:?usage: build_venvs.sh <target-dir> [core-checkout]}"
CORE_CHECKOUT="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

PY="${BACKCOMPAT_PYTHON:-python3.11}"
mkdir -p "$TARGET"

have_uv() { command -v uv >/dev/null 2>&1; }

mkvenv() {
  local name="$1"; shift
  local dir="$TARGET/$name"
  echo "==> building $name"
  if have_uv; then
    uv venv --python "$PY" "$dir" >/dev/null
    VIRTUAL_ENV="$dir" uv pip install --quiet --prerelease=allow "$@"
  else
    "$PY" -m venv "$dir"
    "$dir/bin/pip" install --quiet --upgrade pip
    "$dir/bin/pip" install --quiet --pre "$@"
  fi
  echo "    $("$dir/bin/python" -c 'import sys; print(sys.version.split()[0])')"
}

mkvenv venv_skill_old "ovos-workshop==9.3.1a2"
mkvenv venv_skill_new "ovos-workshop @ git+https://github.com/OpenVoiceOS/ovos-workshop@dev"
mkvenv venv_core_old  "ovos-core==2.5.5a2" "ovos-padatious==2.0.0a1" ovos-messagebus pytest pytest-timeout
mkvenv venv_core_new  "$CORE_CHECKOUT" "ovos-padatious>=2.0.1a2" ovos-messagebus pytest pytest-timeout

echo
echo "resolved versions:"
for v in venv_skill_old venv_skill_new venv_core_old venv_core_new; do
  echo "  $v:"
  "$TARGET/$v/bin/python" - <<'EOF' || true
from importlib.metadata import version, PackageNotFoundError
for p in ("ovos-workshop", "ovos-bus-client", "ovos-core", "ovos-padatious",
          "ovos-spec-tools"):
    try:
        print(f"    {p}=={version(p)}")
    except PackageNotFoundError:
        pass
EOF
done
