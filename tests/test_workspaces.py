import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workspaces-test-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / "cloned workspaces"
        self.project.mkdir()
        shutil.copytree(REPO / ".scripts", self.project / ".scripts")
        shutil.copy2(REPO / "Makefile", self.project / "Makefile")
        self.root = self.project
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.home = self.base / "home"
        (self.home / "Workspaces").mkdir(parents=True)
        self.env = dict(os.environ, WORKSPACES_DIR=str(self.outside), HOME=str(self.home))
        for key in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "NAME"):
            self.env.pop(key, None)

    def run_script(self, script, *args, answer="", env=None):
        return subprocess.run(
            ["bash", str(self.project / ".scripts" / script), *args],
            cwd=self.base,
            env=self.env if env is None else env,
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def run_make(self, *args, answer=""):
        return subprocess.run(
            ["make", *args],
            cwd=self.project,
            env=self.env,
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_failed(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def entries(self):
        return sorted(p.name for p in self.root.iterdir() if p.name not in (".scripts", "Makefile"))

    def populate(self, *names):
        for name in names:
            path = self.root / name
            path.mkdir()
            (path / "marker").write_text(name)

    def test_create_named_and_unnamed(self):
        self.assert_ok(self.run_script("new.sh"))
        self.assert_ok(self.run_script("new.sh", "мой-проект"))
        self.assert_ok(self.run_script("new.sh", ""))
        self.assertEqual(self.entries(), ["01", "02-мой-проект", "03"])

    def test_create_uses_only_valid_directories_and_decimal_prefixes(self):
        self.populate("00", "08-demo", "9-bad", "099-bad", "90bad", "99-")
        (self.root / "98-file").write_text("keep")
        (self.root / "97-link").symlink_to(self.root / "08-demo", target_is_directory=True)
        self.assert_ok(self.run_script("new.sh", "next"))
        self.assertTrue((self.root / "09-next").is_dir())

    def test_create_stops_at_99(self):
        self.populate("98-old")
        self.assert_ok(self.run_script("new.sh"))
        before = self.entries()
        self.assert_failed(self.run_script("new.sh", "overflow"))
        self.assertEqual(self.entries(), before)
        self.assertNotIn("100-overflow", self.entries())

    def test_invalid_names_and_extra_arguments_do_not_create_directories(self):
        for args in (("nested/path",), ("../escape",), ("a\nb",), ("a\rb",), ("learning c",), ("a\tb",), ("a", "b")):
            with self.subTest(args=args):
                self.assert_failed(self.run_script("new.sh", *args))
                self.assertEqual(self.entries(), [])

    def test_special_characters_are_literal(self):
        name = "кавычки'\";$(id)*-"
        self.assert_ok(self.run_script("new.sh", name))
        self.assertEqual(self.entries(), ["01-" + name])
        self.assertFalse((self.root / "injected").exists())
        self.assertFalse((self.root / "injected2").exists())

    def test_existing_file_or_dangling_symlink_is_not_overwritten(self):
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                path = self.root / "01"
                if kind == "file":
                    path.write_text("keep")
                else:
                    path.symlink_to(self.root / "missing")
                self.assert_failed(self.run_script("new.sh"))
                if kind == "file":
                    self.assertEqual(path.read_text(), "keep")
                else:
                    self.assertTrue(path.is_symlink())
                path.unlink()

    def test_scripts_use_their_repository_from_another_working_directory(self):
        self.populate("03-old")
        (self.base / "90-unrelated").mkdir()
        (self.outside / "80-unrelated").mkdir()
        (self.home / "Workspaces" / "70-unrelated").mkdir()
        self.assert_ok(self.run_script("new.sh", "next"))
        self.assert_ok(self.run_script("renumber.sh", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old", "02-next"])
        self.assertTrue((self.base / "90-unrelated").is_dir())
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ["80-unrelated"])
        self.assertEqual(sorted(p.name for p in (self.home / "Workspaces").iterdir()), ["70-unrelated"])

    def test_repository_can_be_moved_before_creating_and_renumbering(self):
        self.populate("05-old")
        previous = self.project
        moved = self.base / "another location" / "workspaces"
        moved.parent.mkdir()
        previous.rename(moved)
        self.project = self.root = moved
        self.assert_ok(self.run_make("new", "NAME=next-project"))
        self.assertEqual(self.entries(), ["05-old", "06-next-project"])
        self.assert_ok(self.run_script("renumber.sh", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old", "02-next-project"])
        self.assertTrue((moved / ".scripts" / "new.sh").is_file())
        self.assertFalse(previous.exists())
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertEqual(list((self.home / "Workspaces").iterdir()), [])

    def test_no_environment_configuration_is_required(self):
        env = dict(self.env)
        env.pop("WORKSPACES_DIR")
        env.pop("HOME")
        self.assert_ok(self.run_script("new.sh", "next", env=env))
        self.assert_ok(self.run_script("renumber.sh", env=env))
        self.assertEqual(self.entries(), ["01-next"])

    def test_scripts_directory_is_not_renumbered(self):
        self.populate("03-old")
        internal = self.project / ".scripts" / "05-internal"
        internal.mkdir()
        (internal / "marker").write_text("keep")
        self.assert_ok(self.run_script("renumber.sh", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old"])
        self.assertEqual((internal / "marker").read_text(), "keep")

    def test_renumber_mixed_formats_preserves_contents(self):
        self.populate("00-start", "03", "08-мой проект", "08-z", "99")
        self.assert_ok(self.run_script("renumber.sh", answer="yes\n"))
        expected = {
            "01-start": "00-start", "02": "03", "03-z": "08-z",
            "04-мой проект": "08-мой проект", "05": "99",
        }
        self.assertEqual(self.entries(), sorted(expected))
        for name, original in expected.items():
            self.assertEqual((self.root / name / "marker").read_text(), original)

    def test_renumber_handles_source_target_overlap(self):
        self.populate("00-same", "01-same", "02")
        self.assert_ok(self.run_script("renumber.sh", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-same", "02-same", "03"])
        self.assertEqual((self.root / "01-same" / "marker").read_text(), "00-same")
        self.assertEqual((self.root / "02-same" / "marker").read_text(), "01-same")
        self.assertEqual((self.root / "03" / "marker").read_text(), "02")

    def test_renumber_is_idempotent_and_ignores_unrelated_entries(self):
        self.populate("01", "02-demo", "1-short", "003-long", "90invalid", "99-")
        (self.root / "98-file").write_text("keep")
        (self.root / "97-link").symlink_to(self.root / "02-demo", target_is_directory=True)
        before = self.entries()
        for _ in range(2):
            self.assert_ok(self.run_script("renumber.sh"))
            self.assertEqual(self.entries(), before)

    def test_empty_directory_and_extra_renumber_arguments(self):
        self.assert_ok(self.run_script("renumber.sh"))
        self.assert_failed(self.run_script("renumber.sh", "unexpected"))
        self.assertEqual(self.entries(), [])

    def test_renumber_cancel_eof_and_invalid_answer(self):
        self.populate("03-name")
        self.assert_ok(self.run_script("renumber.sh", answer="no\n"))
        self.assertEqual(self.entries(), ["03-name"])
        self.assert_failed(self.run_script("renumber.sh"))
        self.assertEqual(self.entries(), ["03-name"])
        self.assert_ok(self.run_script("renumber.sh", answer="maybe\nYes\n"))
        self.assertEqual(self.entries(), ["01-name"])

    def test_renumber_rejects_more_than_99_workspaces(self):
        self.populate(*(f"01-name-{i:03d}" for i in range(100)))
        before = self.entries()
        self.assert_failed(self.run_script("renumber.sh", answer="yes\n"))
        self.assertEqual(self.entries(), before)

    def test_renumber_does_not_overwrite_files_or_links(self):
        self.populate("03-demo")
        target = self.root / "01-demo"
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                if kind == "file":
                    target.write_text("keep")
                else:
                    target.symlink_to(self.root / "missing")
                self.assert_failed(self.run_script("renumber.sh", answer="yes\n"))
                self.assertEqual((self.root / "03-demo" / "marker").read_text(), "03-demo")
                if kind == "file":
                    self.assertEqual(target.read_text(), "keep")
                else:
                    self.assertTrue(target.is_symlink())
                self.assertEqual(self.entries(), ["01-demo", "03-demo"])
                target.unlink()

    def test_rollback_after_move_failure(self):
        self.populate("00-same", "01-same", "03")
        before = self.entries()
        bin_dir = self.base / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "mv"
        wrapper.write_text(
            '#!/usr/bin/env bash\n'
            'count=0\n'
            'if [[ -f "$MOVE_COUNT" ]]; then read -r count < "$MOVE_COUNT"; fi\n'
            'count=$((count + 1))\n'
            'printf "%s\\n" "$count" > "$MOVE_COUNT"\n'
            'if [[ "$count" == "$FAIL_AT" ]]; then exit 1; fi\n'
            'exec "$REAL_MV" "$@"\n'
        )
        wrapper.chmod(0o755)
        for fail_at in (1, 2, 4, 6):
            with self.subTest(fail_at=fail_at):
                count_file = self.base / f"count-{fail_at}"
                env = dict(
                    self.env, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                    MOVE_COUNT=str(count_file), FAIL_AT=str(fail_at), REAL_MV=shutil.which("mv"),
                )
                self.assert_failed(self.run_script("renumber.sh", answer="yes\n", env=env))
                self.assertEqual(self.entries(), before)
                for name in before:
                    self.assertEqual((self.root / name / "marker").read_text(), name)

    def test_make_accepts_name(self):
        self.assert_ok(self.run_make("new", "NAME=learning-c"))
        self.assertEqual(self.entries(), ["01-learning-c"])

    def test_make_rejects_whitespace_even_when_quoted(self):
        self.populate("05-old")
        for command in ("new", "all"):
            for name in ("learning c", "learning ", "learning\tc"):
                with self.subTest(command=command, name=name):
                    self.assert_failed(self.run_make(command, "NAME=" + name, answer="yes\n"))
                    self.assertEqual(self.entries(), ["05-old" if command == "new" else "01-old"])

    def test_make_all_with_name_renumbers_then_creates(self):
        self.populate("05-old")
        self.assert_ok(self.run_make("-j4", "all", "NAME=learning-c", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old", "02-learning-c"])

    def test_make_name_can_match_an_existing_file_or_a_command(self):
        (self.root / "learning-c").mkdir()
        (self.root / "learning.c").write_text("keep")
        for i, name in enumerate(("learning-c", "help", "test", "renumber", "all", "new", "Makefile", "learning.c", "learning.o"), 1):
            with self.subTest(name=name):
                self.assert_ok(self.run_make("new", "NAME=" + name))
                self.assertTrue((self.root / f"{i:02d}-{name}").is_dir())

    def test_make_all_renumbers_before_rejecting_invalid_name(self):
        self.populate("05-old")
        for name in ("nested/path", "a\nb", "a\rb"):
            with self.subTest(name=name):
                self.assert_failed(self.run_make("all", "NAME=" + name, answer="yes\n"))
                self.assertEqual(self.entries(), ["01-old"])

    def test_make_new_without_name(self):
        self.assert_ok(self.run_make("new"))
        self.assertEqual(self.entries(), ["01"])

    def test_make_without_target_only_shows_help(self):
        self.populate("03-demo")
        self.assert_ok(self.run_make())
        self.assertEqual(self.entries(), ["03-demo"])

    def test_make_all_renumbers_before_creating_even_with_parallel_jobs(self):
        self.populate("05-old")
        self.assert_ok(self.run_make("-j4", "all", "NAME=next-project", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old", "02-next-project"])

    def test_make_all_stops_after_renumber_error(self):
        self.populate("05-old")
        (self.root / "01-old").write_text("keep")
        self.assert_failed(self.run_make("all", "NAME=next", answer="yes\n"))
        self.assertEqual(self.entries(), ["01-old", "05-old"])


if __name__ == "__main__":
    unittest.main()
