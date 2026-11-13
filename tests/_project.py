"""What every test module shares: a throwaway project, a copy of a fixture
folder, the findings a run printed.

python3 tests/test_checks.py            # all
    python3 tests/test_checks.py -k luw     # unittest's name filter

WHY THIS EXISTS
---------------
A rule that matches nothing reads exactly like a rule that works. On a clean
package every check prints `ok`, and so would a check whose regex broke last
week. Each test here builds a throwaway project -- abapcheck.toml plus a few
source files -- runs the real script on it, and asserts the finding, so a
check that silently stopped matching fails here first.

Standard library only, like the checks.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


class Project:
    """A throwaway project: files under it, the config at its root."""

    def __init__(self, files, config=""):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "abapcheck.toml").write_text(textwrap.dedent(config))
        (self.root / "src").mkdir()
        for name, text in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(text).lstrip("\n"))

    def run(self, script, *args):
        env = {k: v for k, v in os.environ.items() if k != "ABAPCHECK_CONFIG"}
        r = subprocess.run([sys.executable, str(HERE / script), *args],
                           cwd=self.root, capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr

    def close(self):
        self._tmp.cleanup()


def project(files, config=""):
    return Project(files, config)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name):
    """A throwaway copy of `tests/fixtures/<name>`: a whole project, for checks
    that need more objects than read well inline."""
    p = Project({})
    shutil.copytree(FIXTURES / name, p.root, dirs_exist_ok=True)
    return p


def crosses(out):
    """The findings a run reported: each `✗` line, without the mark."""
    return [l.strip()[2:] for l in out.splitlines() if l.strip().startswith("✗")]


class SuppressionAsserts:
    """Asserts for a suppression round trip: one entry per check, each used,
    none stale, and the finding it names gone."""

    def assert_excused(self, out, entries):
        self.assertIn("ok   suppressions", out)
        for check, key, gone in entries:
            self.assertIn(f"suppressed: {key} - looked", out, (check, key))
            self.assertFalse([f for f in crosses(out) if gone in f], (check, key))

    @staticmethod
    def suppressing(config, entries):
        """CONFIG with a [suppress.<script>.<check>] table per check named."""
        tables = {}
        for script, check, key, _ in entries:
            tables.setdefault(f"{script}.{check}", []).append(key)
        return config + "".join(f"\n[suppress.{t}]\n" + "".join(f"'{k}' = \"looked\"\n" for k in keys)
                                for t, keys in tables.items())

    def run_fixture(self, name, entries, *scripts, before=()):
        p = fixture(name)
        cfg = p.root / "abapcheck.toml"
        cfg.write_text(self.suppressing(cfg.read_text(), entries))
        for gen in before:
            p.run(gen)
        outs = {script: p.run(script)[1] for script in scripts}
        p.close()
        return outs


# A small interface and class every standing check has something to say about.
IFACE = """
INTERFACE zif_a PUBLIC.
  TYPES mty_x TYPE i.
  METHODS run.
  METHODS unused.
ENDINTERFACE.
"""

CLASS = """
CLASS zcl_a DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    INTERFACES zif_a.
    TYPES ty_bad TYPE i.
    METHODS constructor.
  PROTECTED SECTION.
  PRIVATE SECTION.
    DATA _mv_kept TYPE i.
    DATA _mv_lost TYPE i.
    METHODS _dead.
    METHODS _used.
    METHODS unprefixed.
ENDCLASS.

CLASS zcl_a IMPLEMENTATION.
  METHOD constructor.
    _mv_lost = 1.
    _mv_kept = 2.
    _used( ).
    unprefixed( ).
  ENDMETHOD.
  METHOD zif_a~run.
    DATA lt_rows TYPE STANDARD TABLE OF i WITH EMPTY KEY.
    LOOP AT lt_rows INTO DATA(lv_row).
    ENDLOOP.
    cl_demo=>show( _mv_kept ).
    " zif_b=>nothing is prose, not a reference
  ENDMETHOD.
  METHOD zif_a~unused.
  ENDMETHOD.
  METHOD _dead.
  ENDMETHOD.
  METHOD _used.
    DATA(lo_a) = NEW zcl_a( ).
    lo_a->zif_a~run( ).
    DATA(lv) = zif_a=>missing.
  ENDMETHOD.
  METHOD unprefixed.
  ENDMETHOD.
ENDCLASS.
"""
