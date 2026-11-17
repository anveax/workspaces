# workspaces

A Python CLI for numbered project directories in this repository's root.

Requires Python 3.11 or newer. No packages, build step, installation, or configuration.

## Usage

Clone the repository anywhere and run these commands from its root:

```sh
./ws new
./ws new learning-c
./ws list
./ws renumber
./ws renumber --apply
```

On Windows, use `python ws` instead of `./ws`. On other systems, `python3 ws` also works.
Run `./ws --help` or `./ws COMMAND --help` for command help.

| Command | Behavior |
| --- | --- |
| `new [name]` | Create an empty directory using the highest existing number plus one. |
| `list` | Print recognized workspaces in numeric order. |
| `renumber` | Preview consecutive numbering starting at `01`. Change nothing. |
| `renumber --apply` | Apply consecutive numbering, preserving names and contents. |

The first workspace is `01`. A name adds a suffix, such as `02-learning-c`.
New workspaces do not fill gaps. With `01` and `03-learning-c`, `new` creates `04`.
Renumbering changes `03-learning-c` to `02-learning-c`.

## Directory rules

- Only real directories directly beside `ws` are recognized.
- Numbers range from `01` to `99`, always with two digits. `00` is invalid.
- A name is optional. Named directories use `NN-name`.
- Names contain lowercase ASCII letters and digits, separated by single hyphens.
- Spaces, uppercase letters, underscores, repeated hyphens, and leading or trailing hyphens are invalid.
- Other directories, files, and symbolic links are left unchanged. No recursive discovery.
- Duplicate numbers are allowed during discovery. Renumbering sorts by number, then by full directory name.
- Creation stops after `99`; renumbering rejects more than 99 workspaces.

```text
workspaces/
  ws
  README.md
  tests/
  docs/
  01/
  03-learning-c/
```

Here, only `01` and `03-learning-c` are workspaces. `docs` and `tests` are untouched.

The root is derived from the script's resolved location, including when invoked through a symbolic link.
The current working directory does not affect it. Moving or renaming the repository requires no changes.

## Renumbering and recovery

Renumbering checks destination conflicts before moving anything. Files and symbolic links at destination
paths block the operation. Changed directories pass through a temporary `.ws-renumber-*` directory.
Ordinary filesystem errors and Ctrl+C during directory moves trigger an attempt to restore original names.
An incomplete rollback reports the remaining paths and preserves `plan.json` in the temporary directory.
Writes are blocked while a `.ws-renumber-*` recovery directory remains; listing and previewing still work.

Creation and applied renumbering use `.ws.lock` to prevent simultaneous writes by this tool.
Do not manually move affected directories while renumbering. A forced termination or power loss can leave
the lock and a recovery directory behind; automatic crash recovery is not provided.

After an interrupted operation:

1. Make sure no `ws` process is still running.
2. If `.ws-renumber-*` remains, inspect its `plan.json`. Each entry records the original `source` name and
   intended `destination` name. Restore original names from the temporary directory or completed destinations
   without replacing existing paths. Keep the recovery directory until every workspace is accounted for.
   If there is no manifest, remove the directory only if it is empty.
3. Remove the empty recovery directory after removing its `plan.json`.
4. Remove the empty `.ws.lock` directory if it remains, then run `./ws list`.

## Git and tests

Numbered directories are ignored by Git by default and may contain independent repositories.
Remove the two numbered-directory patterns from `.gitignore` to track their contents here.
Git does not track empty directories. Renumbering moves directories, not external references to their paths.

```sh
python3 -m unittest discover -s tests -v
```

On Windows, use `python` instead of `python3`. Tests use temporary repositories.
GitHub Actions runs them on Linux, macOS, and Windows with Python 3.11, 3.13, and 3.14.

Exit codes: `0` success, `1` filesystem or workspace error, `2` invalid arguments,
`130` an interruption outside the renumbering transaction. A rolled-back transaction reports `1`.

## License

MIT. See [LICENSE](LICENSE).
