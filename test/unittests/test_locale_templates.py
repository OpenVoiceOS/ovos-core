"""Validate that every locale resource template shipped with the package expands."""
import os
import unittest

from ovos_spec_tools.expansion import expand

import ovos_core

PACKAGE_ROOT = os.path.dirname(ovos_core.__file__)
TEMPLATE_EXTENSIONS = (".voc", ".intent", ".dialog", ".entity", ".rx")


def iter_locale_files():
    """Yield every template resource file under any locale/ directory."""
    for root, _dirs, files in os.walk(PACKAGE_ROOT):
        parts = root.split(os.sep)
        if "locale" not in parts and "res" not in parts:
            continue
        for fname in files:
            if fname.endswith(TEMPLATE_EXTENSIONS):
                yield os.path.join(root, fname)


class TestLocaleTemplates(unittest.TestCase):
    def test_all_templates_expand(self):
        failures = []
        checked = 0
        for path in iter_locale_files():
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    checked += 1
                    try:
                        expand(line)
                    except Exception as e:
                        rel = os.path.relpath(path, PACKAGE_ROOT)
                        failures.append(f"{rel}:{lineno}: {line!r} -> {e}")
        self.assertGreater(checked, 0, "no locale template lines found")
        self.assertEqual(
            failures, [],
            "malformed locale templates:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
