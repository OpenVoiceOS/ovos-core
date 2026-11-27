"""Exit 1 when a page names a bus topic, config key or ID that the code does not hold."""
import re
import sys
from pathlib import Path

TOKEN = re.compile(r"`([a-z][a-z0-9_-]*(?:[.:][a-z0-9_{}<>-]+)+|ovos-[a-z0-9-]+|[a-z]+(?:_[a-z0-9]+)+)`")
page = Path(sys.argv[1])
text = "\n".join(l for l in page.read_text().splitlines() if not l.startswith(("verify:", "source:")))
corpus = "\n".join(p.read_text(errors="ignore") for d in ("ovos_core", ".github")
                   for p in Path(d).rglob("*") if p.is_file() and p.suffix in {".py", ".yml", ".json", ".voc", ".intent", ".dialog"})
corpus += Path("pyproject.toml").read_text()
skip = set(sys.argv[2:])


def word(w):
    return re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", corpus) is not None


def held(token):
    if token.startswith(("<skill_id>", "<pipeline_id>")):
        return token.split(">", 1)[1] in corpus and token[1:token.index(">")] in ("skill_id", "pipeline_id")
    if token.endswith("_seconds") and word(token[:-8] + "_ms"):
        return True
    if word(token):
        return True
    return all(word(p) for p in re.split(r"[.:]", token))


missing = sorted({t for t in TOKEN.findall(text) if t not in skip and not t.endswith(".md") and not held(t)})
for t in missing:
    print("not in code:", t)
sys.exit(1 if missing else 0)
