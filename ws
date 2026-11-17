#!/usr/bin/env python3

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from types import TracebackType


MAX_NUMBER = 99
NAME_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WORKSPACE_PATTERN = re.compile(r"(?:0[1-9]|[1-9][0-9])(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?")


class WorkspaceError(Exception):
    pass


class RepositoryLock:
    def __init__(self, root: Path) -> None:
        self.path = root / ".ws.lock"

    def __enter__(self) -> "RepositoryLock":
        try:
            self.path.mkdir()
        except FileExistsError as error:
            raise WorkspaceError(
                ".ws.lock already exists. Another operation may be running. "
                "If it was interrupted, follow the recovery instructions in README.md."
            ) from error
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.path.rmdir()


def workspace_key(path: Path) -> tuple[int, str]:
    return (int(path.name[:2]), path.name)


def find_workspaces(root: Path) -> list[Path]:
    workspaces: list[Path] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if WORKSPACE_PATTERN.fullmatch(entry.name) is None:
                continue
            if entry.is_dir(follow_symlinks=False):
                workspaces.append(root / entry.name)
    workspaces.sort(key=workspace_key)
    return workspaces


def validate_name(name: str) -> str:
    if NAME_PATTERN.fullmatch(name) is None:
        raise argparse.ArgumentTypeError(
            "use lowercase ASCII letters and digits, separated by single hyphens"
        )
    return name


def ensure_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise WorkspaceError(f"Destination already exists: {path.name}")


def ensure_no_recovery(root: Path) -> None:
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.name.startswith(".ws-renumber-"):
                continue
            if entry.is_dir(follow_symlinks=False):
                raise WorkspaceError(
                    f"Recovery directory exists: {entry.name}. "
                    "Follow the recovery instructions in README.md before writing."
                )


def directory_identity(path: Path) -> tuple[int, int]:
    information = path.lstat()
    if not stat.S_ISDIR(information.st_mode):
        raise WorkspaceError(f"Expected a directory without a symbolic link: {path}")
    return (information.st_dev, information.st_ino)


def has_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        information = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(information.st_mode) and (
        information.st_dev, information.st_ino
    ) == identity


def rename_directory(
    source: Path, destination: Path, identity: tuple[int, int]
) -> None:
    if directory_identity(source) != identity:
        raise WorkspaceError(f"Directory changed during the operation: {source}")
    ensure_absent(destination)
    source.rename(destination)


def create_workspace(root: Path, name: str | None) -> Path:
    workspaces = find_workspaces(root)
    number = 1
    if len(workspaces) > 0:
        number = int(workspaces[-1].name[:2]) + 1
    if number > MAX_NUMBER:
        raise WorkspaceError("Number 99 is already in use. Renumber to remove gaps.")
    directory_name = f"{number:02d}"
    if name is not None:
        directory_name = directory_name + "-" + name
    destination = root / directory_name
    try:
        destination.mkdir()
    except FileExistsError as error:
        raise WorkspaceError(f"Destination already exists: {directory_name}") from error
    return destination


def make_plan(root: Path) -> list[tuple[Path, Path]]:
    workspaces = find_workspaces(root)
    if len(workspaces) > MAX_NUMBER:
        raise WorkspaceError("More than 99 workspaces cannot fit into two-digit numbering.")
    sources = set(workspaces)
    plan: list[tuple[Path, Path]] = []
    for number, source in enumerate(workspaces, start=1):
        destination = root / (f"{number:02d}" + source.name[2:])
        if destination not in sources:
            ensure_absent(destination)
        plan.append((source, destination))
    return plan


def remove_staging(staging: Path) -> None:
    (staging / "plan.json").unlink(missing_ok=True)
    staging.rmdir()


def apply_plan(root: Path, plan: list[tuple[Path, Path]]) -> None:
    changes: list[tuple[Path, Path, tuple[int, int]]] = []
    for source, destination in plan:
        if source != destination:
            changes.append((source, destination, directory_identity(source)))
    if len(changes) == 0:
        return
    staging = Path(tempfile.mkdtemp(prefix=".ws-renumber-", dir=root))
    attempted: list[tuple[Path, Path, tuple[int, int]]] = []
    try:
        records: list[dict[str, str]] = []
        for source, destination, identity in changes:
            records.append({"source": source.name, "destination": destination.name})
        with (staging / "plan.json").open("x", encoding="utf-8", newline="\n") as manifest:
            json.dump(records, manifest, indent=2)
            manifest.write("\n")
        for source, destination, identity in changes:
            temporary = staging / source.name
            attempted.append((source, temporary, identity))
            rename_directory(source, temporary, identity)
        for source, destination, identity in changes:
            temporary = staging / source.name
            attempted.append((temporary, destination, identity))
            rename_directory(temporary, destination, identity)
    except (OSError, WorkspaceError, KeyboardInterrupt) as error:
        recovery_errors: list[str] = []
        for source, destination, identity in reversed(attempted):
            try:
                if not has_identity(source, identity):
                    rename_directory(destination, source, identity)
            except (OSError, WorkspaceError) as recovery_error:
                recovery_errors.append(f"{destination} -> {source}: {recovery_error}")
        if len(recovery_errors) > 0:
            details = "\n".join(recovery_errors)
            raise WorkspaceError(
                f"Renumbering failed: {error}\n"
                f"Recovery is incomplete. Keep {staging} and its plan.json.\n{details}"
            ) from error
        try:
            remove_staging(staging)
        except OSError as cleanup_error:
            raise WorkspaceError(
                f"Renumbering failed: {error}\nOriginal names restored. "
                f"Could not remove {staging}: {cleanup_error}"
            ) from error
        raise WorkspaceError(f"Renumbering failed: {error}\nOriginal names restored.") from error
    try:
        remove_staging(staging)
    except OSError as error:
        raise WorkspaceError(
            f"Renumbering completed, but could not remove {staging}: {error}"
        ) from error


def renumber_workspaces(root: Path, apply: bool) -> None:
    plan = make_plan(root)
    if len(plan) == 0:
        print("No workspaces.")
        return
    changed = False
    for source, destination in plan:
        if source != destination:
            changed = True
            break
    if not changed:
        print("Already numbered consecutively.")
        return
    if apply:
        apply_plan(root, plan)
    for source, destination in plan:
        print(f"{source.name} -> {destination.name}")
    if not apply:
        print("Preview only. Apply with: ./ws renumber --apply")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ws", description="Manage numbered workspaces beside this script.", allow_abbrev=False
    )
    commands = parser.add_subparsers(dest="command", required=True)
    new_parser = commands.add_parser(
        "new", help="create the next workspace", allow_abbrev=False
    )
    new_parser.add_argument("name", nargs="?", type=validate_name, help="optional hyphenated name")
    commands.add_parser("list", help="list workspaces in numeric order", allow_abbrev=False)
    renumber_parser = commands.add_parser(
        "renumber", help="preview consecutive numbering", allow_abbrev=False
    )
    renumber_parser.add_argument(
        "--apply", action="store_true", help="apply the renumbering instead of previewing it"
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        root = Path(__file__).resolve(strict=True).parent
        if options.command == "list":
            workspaces = find_workspaces(root)
            if len(workspaces) == 0:
                print("No workspaces.")
            for workspace in workspaces:
                print(workspace.name)
        elif options.command == "new":
            with RepositoryLock(root):
                ensure_no_recovery(root)
                destination = create_workspace(root, options.name)
            print(f"Created: {destination.name}")
        elif options.command == "renumber":
            if options.apply:
                with RepositoryLock(root):
                    ensure_no_recovery(root)
                    renumber_workspaces(root, apply=True)
            else:
                renumber_workspaces(root, apply=False)
        else:
            raise WorkspaceError(f"Unknown command: {options.command}")
    except (OSError, WorkspaceError) as error:
        print(f"ws: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ws: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
