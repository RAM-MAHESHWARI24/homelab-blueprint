#!/usr/bin/env python3
"""
Module contract for apps/<module>/ folders (Stage B4).

Every folder under apps/ is a module. Published modules are copied to their own
read-only repo on each release (git subtree split, see docs/RELEASING.md), so they
must work on their own and must never reach outside their folder:

* module.json is valid and names only installer module ids that exist;
  no id is claimed by two modules.
* Published modules carry README.md, LICENSE, an example config, install.sh and
  ci.sh (both executable in git) and .github/workflows/ci.yml that runs ci.sh.
* No file refers to another module's folder (apps/<other>/, / "<other>") and no
  relative path climbs out of the module (../ that resolves outside it).

Run: python testing/test_module_contract.py
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS = REPO_ROOT / "apps"
sys.path.insert(0, str(REPO_ROOT))

# File types whose contents are checked for out-of-folder references. Docs are
# excluded on purpose: a README may link to the blueprint.
CODE_SUFFIXES = {".py", ".sh", ".yml", ".yaml", ".json", ".js", ".conf", ".example", ".service", ""}
# The installer's env renderer writes every module's .env, so it has to know them all.
# It lives in control-hub's shared config_core because both setup/ and the Control Hub
# import it, which the module rules allow (setup/ may import from apps/control-hub).
REACH_EXEMPT = {"apps/control-hub/core/config_core/env_manager.py"}
REQUIRED_KEYS = {"name", "description", "publish", "repo", "split_secret", "blueprint_modules", "standalone"}


def module_dirs():
    return sorted(p for p in APPS.iterdir() if p.is_dir() and not p.name.startswith((".", "__")))


def tracked_files(module: Path):
    out = subprocess.run(["git", "ls-files", "-s", str(module.relative_to(REPO_ROOT))],
                         cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        files[path] = meta.split()[0]  # git file mode, e.g. 100755
    return files


def load_manifest(module: Path):
    return json.loads((module / "module.json").read_text(encoding="utf-8"))


class TestModuleContract(unittest.TestCase):
    def test_every_module_has_a_valid_manifest(self):
        for module in module_dirs():
            with self.subTest(module=module.name):
                self.assertTrue((module / "module.json").is_file(), "module.json missing")
                data = load_manifest(module)
                self.assertEqual(REQUIRED_KEYS - set(data), set(), "module.json keys missing")
                self.assertIsInstance(data["publish"], bool)
                self.assertIsInstance(data["blueprint_modules"], list)
                if data["publish"]:
                    self.assertRegex(data["repo"] or "", r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
                    self.assertRegex(data["split_secret"] or "", r"^SPLIT_KEY_[A-Z0-9_]+$")
                    self.assertEqual(data["standalone"].get("install"), "install.sh")

    def test_installer_module_ids_exist_and_are_claimed_once(self):
        from setup.installer.deployer import MODULE_ORDER

        claimed = {}
        for module in module_dirs():
            for mod_id in load_manifest(module)["blueprint_modules"]:
                with self.subTest(module=module.name, id=mod_id):
                    self.assertIn(mod_id, MODULE_ORDER, "unknown installer module id")
                    self.assertNotIn(mod_id, claimed, f"also claimed by {claimed.get(mod_id)}")
                    claimed[mod_id] = module.name

    def test_published_modules_carry_their_standalone_files(self):
        for module in module_dirs():
            data = load_manifest(module)
            if not data["publish"]:
                continue
            files = tracked_files(module)
            prefix = f"apps/{module.name}/"

            def rel(name, prefix=prefix):
                return prefix + name

            with self.subTest(module=module.name):
                for name in ("README.md", "LICENSE", "module.json", ".github/workflows/ci.yml"):
                    self.assertIn(rel(name), files, f"{name} not tracked")
                self.assertTrue(rel(".env.example") in files or rel("config.example.json") in files,
                                "no example config (.env.example or config.example.json)")
                for script in ("install.sh", "ci.sh"):
                    self.assertEqual(files.get(rel(script)), "100755", f"{script} missing or not executable")
                workflow = (module / ".github/workflows/ci.yml").read_text(encoding="utf-8")
                self.assertIn("ci.sh", workflow, "module workflow does not run ci.sh")

    def test_no_module_reaches_outside_its_folder(self):
        names = [m.name for m in module_dirs()]
        problems = []
        for module in module_dirs():
            alternatives = "|".join(re.escape(n) for n in names if n != module.name)
            # apps/<other>/... in any path, or a Python path join such as APPS / "<other>"
            other_ref = re.compile(rf"apps/(?:{alternatives})\b|/\s*[\"'](?:{alternatives})[\"']")
            for path in tracked_files(module):
                if path in REACH_EXEMPT:
                    continue
                file = REPO_ROOT / path
                if file.suffix not in CODE_SUFFIXES or not file.is_file():
                    continue
                text = file.read_text(encoding="utf-8", errors="ignore")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if other_ref.search(line):
                        problems.append(f"{path}:{lineno}: refers to another module: {line.strip()[:100]}")
                    for match in re.finditer(r"(?:\.\./)+[\w.\-/]*", line):
                        target = (file.parent / match.group(0)).resolve()
                        if not target.is_relative_to(module.resolve()):
                            problems.append(f"{path}:{lineno}: path leaves the module: {match.group(0)}")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_published_docs_do_not_link_outside_the_module(self):
        """In the published repo, a relative link out of the folder would be broken."""
        problems = []
        for module in module_dirs():
            if not load_manifest(module)["publish"]:
                continue
            for path in tracked_files(module):
                if not path.endswith(".md"):
                    continue
                file = REPO_ROOT / path
                for lineno, line in enumerate(file.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    for target in re.findall(r"\]\(([^)\s#]+)", line):
                        if re.match(r"^[a-z]+:", target):
                            continue  # absolute URL or mailto:
                        resolved = (file.parent / target).resolve()
                        if not resolved.is_relative_to(module.resolve()):
                            problems.append(f"{path}:{lineno}: link leaves the module: {target}")
        self.assertEqual(problems, [], "\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
