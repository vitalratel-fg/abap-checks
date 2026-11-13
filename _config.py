"""Which project a run checks, and what that project says about itself.

    python3 check_x.py                         # project found from the cwd up
    python3 check_x.py --project ../other      # project found from there up
    python3 check_x.py --config cmo/abapcheck.toml

A project is a directory holding `abapcheck.toml`, found by walking up from
the current directory (or from `--project`) the way abaplint finds
abaplint.json. `--config FILE` names it outright, which is how one repository
holding two packages runs each: one config per package, `[package] root`
pointing at its folder. `ABAPCHECK_CONFIG` is the same as `--config`.

The flags are stripped from `sys.argv` at import, so a check's own argument
parsing (check names, structure names) cannot mistake them for its own.

NO CONFIG IS NOT AN ERROR, BUT IT IS SAID. Without one the base is the
current directory, the source root comes from `.abapgit.xml`, and every check
that needs a fact the project has not stated prints `--`, not `ok`: a check
that ran on nothing reads exactly like one that passed, and this suite exists
to keep the two apart.

THREE KINDS OF CHECK, AND WHAT CONFIGURES EACH
  defect       wrong in any package: unresolvable, dead, a dump at runtime.
               Always on.
  convention   house style with a default here (`mty_` types, ASSIGNING
               loops, one table one owner). On; `[checks] off` turns one off.
  fact         needs something only the project knows: which class may
               commit, which names are retired, where the register is. Off
               until the key is set, and its `--` names the key.
"""

import os
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

FILENAME = "abapcheck.toml"


def _consume(argv, *flags):
    """Pull every `FLAG VALUE` / `FLAG=VALUE` for FLAGS out of argv."""
    found, i = [], 0
    while i < len(argv):
        arg = argv[i]
        if arg in flags and i + 1 < len(argv):
            found.append(argv[i + 1])
            del argv[i:i + 2]
            continue
        hit = next((f for f in flags if arg.startswith(f + "=")), None)
        if hit:
            found.append(arg.split("=", 1)[1])
            del argv[i]
            continue
        i += 1
    return found


def _find(start):
    for d in [start, *start.parents]:
        if (d / FILENAME).is_file():
            return d / FILENAME
    return None


_config_arg = _consume(sys.argv, "--config", "-c")
_project_arg = _consume(sys.argv, "--project")
# `--file SUBSTR`: narrow the corpus to files whose path contains SUBSTR. Read
# by _pkg; stripped here so every flag this suite owns is stripped in one place.
FILE_FILTER = _consume(sys.argv, "--file")

_explicit = _config_arg[-1] if _config_arg else os.environ.get("ABAPCHECK_CONFIG")
_start = Path(_project_arg[-1]).resolve() if _project_arg else Path.cwd()

if _explicit:
    CONFIG_FILE = Path(_explicit).resolve()
    if not CONFIG_FILE.is_file():
        raise SystemExit(f"no config at {CONFIG_FILE}")
else:
    CONFIG_FILE = _find(_start)

DATA = tomllib.loads(CONFIG_FILE.read_text()) if CONFIG_FILE else {}

# The project base: what every relative path in the config is relative to.
# `[package] base` overrides it, so a config kept outside the project (a
# scratch copy, a CI file) can still point at the tree it describes.
_base = CONFIG_FILE.parent if CONFIG_FILE else _start
if DATA.get("package", {}).get("base"):
    _base = (_base / DATA["package"]["base"]).resolve()
if _project_arg and _explicit:
    _base = _start
BASE = _base

if CONFIG_FILE is None:
    print(f"NOTE: no {FILENAME} from {_start} up: defaults only, and every "
          f"check that needs a project fact prints `--`.", file=sys.stderr)


_MISSING = object()


def get(dotted, default=None):
    """`get("cds.budget", 40)`: one value from the config, by dotted path."""
    node = DATA
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def has(dotted):
    return get(dotted, _MISSING) is not _MISSING


def path(dotted, default=None):
    """A config path, resolved against BASE; None when unset and no default."""
    value = get(dotted, default)
    return (BASE / value).resolve() if value else None


def disabled(script, check):
    """`[checks] off = ["loops", "cds.abapfree"]`: a convention turned off.

    A bare name turns the check off in every script that has one of that
    name; `script.check` in one script only.
    """
    off = set(get("checks.off", []))
    return check in off or f"{script}.{check}" in off


def suppressions(script):
    """`[suppress.<script>.<check>] "exact key" = "why someone looked"`."""
    return get(f"suppress.{script}", {})


def _abapgit():
    """(starting folder, folder logic) from `.abapgit.xml`, or defaults."""
    f = BASE / ".abapgit.xml"
    if not f.is_file():
        return "src", "PREFIX"
    root = ET.parse(f).getroot()
    start = (root.findtext(".//STARTING_FOLDER") or "/src/").strip("/") or "."
    return start, (root.findtext(".//FOLDER_LOGIC") or "PREFIX")


_start_folder, FOLDER_LOGIC = _abapgit()

# The source root: `[package] root`, else `.abapgit.xml`'s starting folder.
ROOT = (BASE / get("package.root", _start_folder)).resolve()


def regex(dotted, flags=re.I):
    """A compiled regex from the config, or None when unset."""
    value = get(dotted)
    return re.compile(value, flags) if value else None
