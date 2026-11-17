import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "ws"
LOADER = importlib.machinery.SourceFileLoader("workspace_tool", str(SCRIPT))
SPECIFICATION = importlib.util.spec_from_loader(LOADER.name, LOADER)
if SPECIFICATION is None:
    raise RuntimeError("Could not load the workspace tool.")
ws = importlib.util.module_from_spec(SPECIFICATION)
LOADER.exec_module(ws)


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ws tests ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "checkout with spaces"
        self.root.mkdir()
        shutil.copyfile(SCRIPT, self.root / "ws")
        (self.root / "ws").chmod(0o755)
        self.outside = self.base / "outside"
        self.outside.mkdir()

    def run_ws(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(self.root / "ws")]
        command.extend(arguments)
        return subprocess.run(
            command,
            cwd=self.outside,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )

    def workspace(self, name: str, content: str = "") -> Path:
        path = self.root / name
        path.mkdir()
        (path / "content.txt").write_text(content, encoding="utf-8")
        return path

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def assert_no_artifacts(self) -> None:
        self.assertFalse((self.root / ".ws.lock").exists())
        self.assertEqual(list(self.root.glob(".ws-renumber-*")), [])

    def make_symlink(self, path: Path, target: Path) -> None:
        try:
            path.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic links unavailable: {error}")

    def test_create_unnamed_and_named_workspaces(self) -> None:
        first = self.run_ws("new")
        second = self.run_ws("new", "learning-cmake-2")
        self.assert_success(first)
        self.assert_success(second)
        self.assertEqual(first.stdout, "Created: 01\n")
        self.assertEqual(second.stdout, "Created: 02-learning-cmake-2\n")
        self.assertEqual(list((self.root / "01").iterdir()), [])
        self.assertEqual(list((self.root / "02-learning-cmake-2").iterdir()), [])
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assert_no_artifacts()

    def test_new_uses_highest_number_and_keeps_gaps(self) -> None:
        self.workspace("01")
        self.workspace("03-learning-c")
        result = self.run_ws("new")
        self.assert_success(result)
        self.assertTrue((self.root / "04").is_dir())
        self.assertFalse((self.root / "02").exists())

    def test_invalid_names_do_not_change_the_repository(self) -> None:
        names = [
            "", "two words", " two", "two ", "-name", "name-", "two--parts",
            "Upper", "under_score", "c++", "café", ".", "..", "../outside",
            "two/parts", "two\\parts", "line\nbreak", str(self.outside),
        ]
        for name in names:
            with self.subTest(name=name):
                result = self.run_ws("new", name)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["ws"])

    def test_numeric_names_are_valid(self) -> None:
        result = self.run_ws("new", "2026")
        self.assert_success(result)
        self.assertTrue((self.root / "01-2026").is_dir())

    def test_list_filters_and_sorts_only_immediate_workspaces(self) -> None:
        for name in ["10-z", "02-b", "02", "01"]:
            self.workspace(name)
        for name in ["docs", "00", "1", "001", "01-Upper", "01-two--parts", "01_bad"]:
            self.workspace(name, "untouched")
        (self.root / "docs" / "03-hidden").mkdir()
        (self.root / "04-file").write_text("file", encoding="utf-8")
        result = self.run_ws("list")
        self.assert_success(result)
        self.assertEqual(result.stdout, "01\n02\n02-b\n10-z\n")

    def test_symbolic_links_are_not_workspaces(self) -> None:
        self.make_symlink(self.root / "90-link", self.outside)
        self.make_symlink(self.root / "91-broken", self.outside / "missing")
        result = self.run_ws("list")
        self.assert_success(result)
        self.assertEqual(result.stdout, "No workspaces.\n")
        result = self.run_ws("new")
        self.assert_success(result)
        self.assertTrue((self.root / "01").is_dir())
        self.assertTrue((self.root / "90-link").is_symlink())
        self.assertTrue((self.root / "91-broken").is_symlink())

    def test_empty_list_and_renumber_do_not_create_artifacts(self) -> None:
        for arguments in [("list",), ("renumber",), ("renumber", "--apply")]:
            with self.subTest(arguments=arguments):
                result = self.run_ws(*arguments)
                self.assert_success(result)
                self.assertEqual(result.stdout, "No workspaces.\n")
                self.assert_no_artifacts()

    def test_preview_preserves_names_contents_and_identities(self) -> None:
        first = self.workspace("01", "first")
        second = self.workspace("03-learning-c", "second")
        identity = second.stat().st_ino
        result = self.run_ws("renumber")
        self.assert_success(result)
        self.assertIn("01 -> 01\n03-learning-c -> 02-learning-c\n", result.stdout)
        self.assertIn("Preview only", result.stdout)
        self.assertEqual(second.stat().st_ino, identity)
        self.assertEqual((first / "content.txt").read_text(), "first")
        self.assertEqual((second / "content.txt").read_text(), "second")
        self.assertFalse((self.root / "02-learning-c").exists())
        self.assert_no_artifacts()

    def test_apply_preserves_nested_contents_and_other_directories(self) -> None:
        self.workspace("01", "first")
        source = self.workspace("03-learning-c", "second")
        nested = source / "nested"
        nested.mkdir()
        (nested / "binary").write_bytes(bytes(range(256)))
        self.workspace("docs", "unrelated")
        self.workspace("00-invalid", "unrecognized")
        result = self.run_ws("renumber", "--apply")
        self.assert_success(result)
        self.assertFalse(source.exists())
        self.assertEqual((self.root / "02-learning-c" / "content.txt").read_text(), "second")
        self.assertEqual((self.root / "02-learning-c" / "nested" / "binary").read_bytes(), bytes(range(256)))
        self.assertEqual((self.root / "docs" / "content.txt").read_text(), "unrelated")
        self.assertEqual((self.root / "00-invalid" / "content.txt").read_text(), "unrecognized")
        self.assert_no_artifacts()

    def test_duplicate_numbers_and_overlapping_destinations(self) -> None:
        self.workspace("01", "unnamed")
        self.workspace("01-a", "duplicate")
        self.workspace("02-a", "next")
        result = self.run_ws("renumber", "--apply")
        self.assert_success(result)
        for name, content in [("01", "unnamed"), ("02-a", "duplicate"), ("03-a", "next")]:
            self.assertEqual((self.root / name / "content.txt").read_text(), content)
        self.assert_no_artifacts()

    def test_duplicate_numbers_sort_by_full_name(self) -> None:
        self.workspace("01-z", "z")
        self.workspace("01-a", "a")
        self.workspace("01", "unnamed")
        result = self.run_ws("renumber", "--apply")
        self.assert_success(result)
        self.assertEqual(result.stdout, "01 -> 01\n01-a -> 02-a\n01-z -> 03-z\n")

    def test_consecutive_numbering_is_a_no_op(self) -> None:
        source = self.workspace("01-a", "keep")
        identity = source.stat().st_ino
        result = self.run_ws("renumber", "--apply")
        self.assert_success(result)
        self.assertEqual(result.stdout, "Already numbered consecutively.\n")
        self.assertEqual(source.stat().st_ino, identity)
        self.assert_no_artifacts()

    def test_file_conflict_blocks_preview_and_apply_before_moves(self) -> None:
        self.workspace("03-a", "a")
        self.workspace("04-b", "b")
        collision = self.root / "02-b"
        collision.write_text("keep", encoding="utf-8")
        for arguments in [("renumber",), ("renumber", "--apply")]:
            with self.subTest(arguments=arguments):
                result = self.run_ws(*arguments)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Destination already exists: 02-b", result.stderr)
                self.assertEqual(collision.read_text(), "keep")
                self.assertTrue((self.root / "03-a").is_dir())
                self.assertTrue((self.root / "04-b").is_dir())
                self.assert_no_artifacts()

    def test_dangling_symlink_blocks_renumbering(self) -> None:
        self.workspace("03-a", "a")
        collision = self.root / "01-a"
        self.make_symlink(collision, self.outside / "missing")
        result = self.run_ws("renumber", "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(collision.is_symlink())
        self.assertTrue((self.root / "03-a").is_dir())
        self.assert_no_artifacts()

    def test_file_conflict_blocks_creation(self) -> None:
        collision = self.root / "01"
        collision.write_text("keep", encoding="utf-8")
        result = self.run_ws("new")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(collision.read_text(), "keep")
        self.assert_no_artifacts()

    def test_dangling_symlink_blocks_creation(self) -> None:
        collision = self.root / "01"
        self.make_symlink(collision, self.outside / "missing")
        result = self.run_ws("new")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(collision.is_symlink())
        self.assert_no_artifacts()

    def test_creation_stops_at_99(self) -> None:
        self.workspace("99-last")
        result = self.run_ws("new")
        self.assertEqual(result.returncode, 1)
        self.assertIn("99", result.stderr)
        self.assertFalse((self.root / "100").exists())
        self.assert_no_artifacts()

    def test_renumbering_reopens_capacity(self) -> None:
        self.workspace("99-last", "keep")
        self.assert_success(self.run_ws("renumber", "--apply"))
        self.assert_success(self.run_ws("new"))
        self.assertTrue((self.root / "02").is_dir())
        self.assertEqual((self.root / "01-last" / "content.txt").read_text(), "keep")

    def test_renumbering_rejects_more_than_99_workspaces(self) -> None:
        for number in range(100):
            (self.root / f"01-item-{number}").mkdir()
        result = self.run_ws("renumber", "--apply")
        self.assertEqual(result.returncode, 1)
        self.assertIn("More than 99", result.stderr)
        self.assertEqual(len(list(self.root.glob("01-item-*"))), 100)
        self.assert_no_artifacts()

    def test_existing_lock_blocks_writes_and_is_preserved(self) -> None:
        lock = self.root / ".ws.lock"
        lock.mkdir()
        marker = lock / "owner"
        marker.write_text("keep", encoding="utf-8")
        for arguments in [("new",), ("renumber", "--apply")]:
            with self.subTest(arguments=arguments):
                result = self.run_ws(*arguments)
                self.assertEqual(result.returncode, 1)
                self.assertIn(".ws.lock already exists", result.stderr)
                self.assertEqual(marker.read_text(), "keep")
        self.assert_success(self.run_ws("list"))
        self.assert_success(self.run_ws("renumber"))

    def test_recovery_directory_blocks_writes(self) -> None:
        recovery = self.root / ".ws-renumber-interrupted"
        recovery.mkdir()
        for arguments in [("new",), ("renumber", "--apply")]:
            with self.subTest(arguments=arguments):
                result = self.run_ws(*arguments)
                self.assertEqual(result.returncode, 1)
                self.assertIn("Recovery directory exists", result.stderr)
                self.assertFalse((self.root / ".ws.lock").exists())
                self.assertTrue(recovery.is_dir())
        self.assert_success(self.run_ws("list"))

    def test_relocating_the_checkout_requires_no_configuration(self) -> None:
        relocated = self.base / "relocated checkout"
        shutil.move(str(self.root), relocated)
        self.root = relocated
        self.assert_success(self.run_ws("new", "relocated"))
        self.assertTrue((relocated / "01-relocated").is_dir())

    def test_script_symlink_resolves_the_repository(self) -> None:
        launcher = self.outside / "launcher"
        try:
            launcher.symlink_to(self.root / "ws")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic links unavailable: {error}")
        result = subprocess.run(
            [sys.executable, str(launcher), "new"],
            cwd=self.outside,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assert_success(result)
        self.assertTrue((self.root / "01").is_dir())
        self.assertFalse((self.outside / "01").exists())

    @unittest.skipIf(os.name == "nt", "Direct shebang execution requires a Unix shell.")
    def test_script_is_directly_executable(self) -> None:
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        result = subprocess.run(
            [str(self.root / "ws"), "new"],
            cwd=self.outside,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assert_success(result)
        self.assertTrue((self.root / "01").is_dir())

    def test_help_and_argument_errors_do_not_modify_the_repository(self) -> None:
        self.assert_success(self.run_ws("--help"))
        for arguments in [(), ("unknown",), ("new", "a", "b"), ("renumber", "--app")]:
            with self.subTest(arguments=arguments):
                result = self.run_ws(*arguments)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["ws"])


class TransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ws transaction ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ["03-a", "04-b"]:
            path = self.root / name
            path.mkdir()
            (path / "content").write_text(name, encoding="utf-8")

    def assert_original_contents(self) -> None:
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["03-a", "04-b"])
        for name in ["03-a", "04-b"]:
            self.assertEqual((self.root / name / "content").read_text(), name)

    def test_failures_at_each_move_restore_original_names(self) -> None:
        original_rename = ws.rename_directory
        for fail_at in range(1, 5):
            for after_move in [False, True]:
                with self.subTest(fail_at=fail_at, after_move=after_move):
                    calls = 0

                    def failing_rename(source: Path, destination: Path, identity: tuple[int, int]) -> None:
                        nonlocal calls
                        calls = calls + 1
                        if calls == fail_at and not after_move:
                            raise OSError("simulated failure")
                        original_rename(source, destination, identity)
                        if calls == fail_at and after_move:
                            raise OSError("simulated failure after rename")

                    with mock.patch.object(ws, "rename_directory", side_effect=failing_rename):
                        with self.assertRaisesRegex(ws.WorkspaceError, "Original names restored"):
                            ws.apply_plan(self.root, ws.make_plan(self.root))
                    self.assert_original_contents()

    def test_keyboard_interrupt_restores_original_names(self) -> None:
        original_rename = ws.rename_directory
        calls = 0

        def interrupted_rename(source: Path, destination: Path, identity: tuple[int, int]) -> None:
            nonlocal calls
            calls = calls + 1
            original_rename(source, destination, identity)
            if calls == 3:
                raise KeyboardInterrupt()

        with mock.patch.object(ws, "rename_directory", side_effect=interrupted_rename):
            with self.assertRaisesRegex(ws.WorkspaceError, "Original names restored"):
                ws.apply_plan(self.root, ws.make_plan(self.root))
        self.assert_original_contents()

    def test_overlapping_destinations_are_restored_after_failures(self) -> None:
        original_rename = ws.rename_directory
        for fail_at in range(1, 5):
            with self.subTest(fail_at=fail_at):
                with tempfile.TemporaryDirectory(dir=self.root) as temporary:
                    root = Path(temporary)
                    for name in ["01", "01-a", "02-a"]:
                        (root / name).mkdir()
                        (root / name / "content").write_text(name, encoding="utf-8")
                    calls = 0

                    def failing_rename(
                        source: Path, destination: Path, identity: tuple[int, int]
                    ) -> None:
                        nonlocal calls
                        calls = calls + 1
                        original_rename(source, destination, identity)
                        if calls == fail_at:
                            raise OSError("simulated failure after rename")

                    with mock.patch.object(ws, "rename_directory", side_effect=failing_rename):
                        with self.assertRaisesRegex(ws.WorkspaceError, "Original names restored"):
                            ws.apply_plan(root, ws.make_plan(root))
                    self.assertEqual(
                        sorted(path.name for path in root.iterdir()), ["01", "01-a", "02-a"]
                    )
                    for name in ["01", "01-a", "02-a"]:
                        self.assertEqual((root / name / "content").read_text(), name)

    def test_incomplete_recovery_preserves_every_workspace_and_manifest(self) -> None:
        original_rename = ws.rename_directory
        calls = 0

        def failing_rename(source: Path, destination: Path, identity: tuple[int, int]) -> None:
            nonlocal calls
            calls = calls + 1
            if calls >= 4:
                raise OSError("simulated persistent failure")
            original_rename(source, destination, identity)

        with mock.patch.object(ws, "rename_directory", side_effect=failing_rename):
            with self.assertRaisesRegex(ws.WorkspaceError, "Recovery is incomplete"):
                ws.apply_plan(self.root, ws.make_plan(self.root))
        staging_directories = list(self.root.glob(".ws-renumber-*"))
        self.assertEqual(len(staging_directories), 1)
        staging = staging_directories[0]
        records = json.loads((staging / "plan.json").read_text())
        self.assertEqual(records, [
            {"source": "03-a", "destination": "01-a"},
            {"source": "04-b", "destination": "02-b"},
        ])
        contents = sorted(path.read_text() for path in self.root.rglob("content"))
        self.assertEqual(contents, ["03-a", "04-b"])
        with self.assertRaisesRegex(ws.WorkspaceError, "Recovery directory exists"):
            ws.ensure_no_recovery(self.root)

    def test_manifest_failure_moves_nothing_and_cleans_up(self) -> None:
        with mock.patch.object(ws.json, "dump", side_effect=OSError("cannot write manifest")):
            with self.assertRaisesRegex(ws.WorkspaceError, "Original names restored"):
                ws.apply_plan(self.root, ws.make_plan(self.root))
        self.assert_original_contents()

    def test_destination_appearing_after_preflight_is_preserved(self) -> None:
        plan = ws.make_plan(self.root)
        collision = self.root / "01-a"
        collision.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ws.WorkspaceError, "Original names restored"):
            ws.apply_plan(self.root, plan)
        self.assertEqual(collision.read_text(), "keep")
        self.assertEqual((self.root / "03-a" / "content").read_text(), "03-a")
        self.assertEqual((self.root / "04-b" / "content").read_text(), "04-b")
        self.assertEqual(list(self.root.glob(".ws-renumber-*")), [])

    def test_replaced_source_is_not_moved(self) -> None:
        source = self.root / "03-a"
        identity = ws.directory_identity(source)
        source.rename(self.root / "saved")
        source.mkdir()
        (source / "content").write_text("replacement", encoding="utf-8")
        with self.assertRaisesRegex(ws.WorkspaceError, "Directory changed"):
            ws.rename_directory(source, self.root / "01-a", identity)
        self.assertEqual((source / "content").read_text(), "replacement")
        self.assertEqual((self.root / "saved" / "content").read_text(), "03-a")
        self.assertFalse((self.root / "01-a").exists())


if __name__ == "__main__":
    unittest.main()
