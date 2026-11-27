"""Exit 1 when a page names a bus topic, config key or ID that the code does not hold."""
import re
import sys
from pathlib import Path

TOKEN = re.compile(r"`(<[a-z_]+>[.:][a-z0-9_.:-]+|[a-z][a-z0-9_-]*(?:[.:][a-z0-9_{}<>-]+)+|ovos-[a-z0-9-]+|[a-z]+(?:_[a-z0-9]+)+)`")
page = Path(sys.argv[1])
text = "\n".join(l for l in page.read_text().splitlines() if not l.startswith(("verify:", "source:")))
corpus = "\n".join(p.read_text(errors="ignore") for d in ("ovos_core", ".github")
                   for p in Path(d).rglob("*") if p.is_file() and p.suffix in {".py", ".yml", ".json", ".voc", ".intent", ".dialog"})
corpus += Path("pyproject.toml").read_text()
skip = set(sys.argv[2:])


def word(w):
    return re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", corpus) is not None


def held(token):
    if token.startswith("<"):
        name, rest = token[1:].split(">", 1)
        return name in ("skill_id", "pipeline_id") and re.search(rf"{re.escape(rest)}(?![\w-])", corpus) is not None
    if token.endswith("_seconds") and word(token[:-8] + "_ms"):
        return True
    if word(token):
        return True
    mod, _, name = token.rpartition(".")
    if mod and (re.search(rf"from {re.escape(mod)} import [^\n]*\b{re.escape(name)}\b", corpus) or word(f"from {token} import") or re.search(rf"from {re.escape(token)} import", corpus)):
        return True
    # a config key such as skills.use_deferred_loading: each part is a quoted string in the code
    return all(f'"{p}"' in corpus or f"'{p}'" in corpus for p in token.split("."))


missing = sorted({t for t in TOKEN.findall(text) if t not in skip and not t.endswith(".md") and not held(t)})
for t in missing:
    print("not in code:", t)
sys.exit(1 if missing else 0)
