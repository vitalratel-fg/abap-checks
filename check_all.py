#!/usr/bin/env python3
"""Every check, one exit code: the hook and CI entry point.

    python3 check_all.py                    # every gate
    python3 check_all.py --with stubs       # plus the stub report
    python3 check_all.py --config x.toml    # passed on to each script

Each script runs in its own process -- they read their config at import --
and its output is printed as it comes. The exit code is the number of
scripts that failed, so a hook can tell "one check found three things" from
"three checks each found one" by reading the output, and from a clean run by
the code.

The generators run in `--check` mode, and only when the config defines
something for them to generate. check_stubs.py is a report, not a gate --
a package in progress has stubs -- so it runs only with `--with stubs`.
"""

import subprocess
import sys
from pathlib import Path

import _config

HERE = Path(__file__).resolve().parent

GATES = ["check_standing.py", "check_design.py", "check_cds.py", "check_app.py",
         "check_luw.py", "check_messages.py", "check_sorted_rows.py",
         "check_bare_bool.py", "check_clobbered_writes.py", "check_model_writers.py"]
GENERATORS = [("make_ddic.py", "ddic"), ("make_meta.py", "meta")]


def main():
    passthrough = []
    if _config.CONFIG_FILE:
        passthrough += ["--config", str(_config.CONFIG_FILE)]
    if _config.BASE != (_config.CONFIG_FILE.parent if _config.CONFIG_FILE else None):
        passthrough += ["--project", str(_config.BASE)]
    for f in _config.FILE_FILTER:
        passthrough += ["--file", f]
    extra = set(_config._consume(sys.argv, "--with"))

    runs = [[s] for s in GATES]
    runs += [[g, "--check"] for g, key in GENERATORS if _config.has(key)]
    if "stubs" in extra:
        runs.append(["check_stubs.py"])

    failed = []
    for script, *args in runs:
        print(f"\n━━ {script} {' '.join(args)}".rstrip(), flush=True)
        rc = subprocess.call([sys.executable, str(HERE / script), *args, *passthrough])
        if rc:
            failed.append(f"{script} ({rc})")
    print(f"\n━━ {len(runs) - len(failed)} of {len(runs)} passed"
          + (f"; failed: {', '.join(failed)}" if failed else ""))
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
