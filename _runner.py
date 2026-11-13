"""How every check script runs its checks.

    python3 check_x.py                  # every check
    python3 check_x.py graph raising    # named checks only
    python3 check_x.py --list

A check is (key, description, fn). `fn()` returns (findings, notes), or a
`Skip` saying why it did not run. A finding is a `Finding(text, key)`: the
runner drops it when `[suppress.<script>.<check>]` names its key, so a check
says what it found and the runner alone decides what is excused. Plain text
is a finding no suppression can name. The return value of `run` is the
number of unsuppressed findings, plus stale suppressions on a full run, so it
is usable as an exit code in a hook.

THREE MARKS, NEVER TWO
  ok    the check ran on something and found nothing
  FAIL  it found something
  --    it ran on nothing (no source, no CDS, no app), was turned off, or
        needs a project fact the config does not state. The note says which.
A check that ran on nothing printing `ok` is the failure this suite exists
to prevent, so `--` is never collapsed into `ok`.
"""

import sys
from collections import namedtuple

import _config
from _suppress import Suppressions

Skip = namedtuple("Skip", "why")
# What a check found, and the exact text a suppression names it by.
Finding = namedtuple("Finding", "text key")


def needs(key):
    """The Skip for a fact check whose config key is unset."""
    return Skip(f"not configured: set `{key}` in {_config.FILENAME}")


def suppressions(script):
    return Suppressions(_config.suppressions(script))


def run(script, checks, suppressed, empty=False, empty_why="no source on disk",
        source_only=()):
    """Run CHECKS, print the report, return the total.

    `source_only`: checks whose verdict is vacuous on an empty corpus. When
    `empty`, they print `--` with `empty_why` instead of running.
    """
    keys = [k for k, _, _ in checks]
    if "--list" in sys.argv:
        return _list(script, checks)
    args = _selected(script, keys)
    if empty:
        print(f"--  {empty_why}: source checks are marked `--`, not `ok`.\n")
    vacuous = {k for k in keys if empty and (k in source_only or not source_only)}
    counts = {c[0]: _run_one(script, c, suppressed, c[0] in vacuous, empty_why)
              for c in checks if not args or c[0] in args}
    total = sum(n for n in counts.values() if n)
    # A filtered run never consults the checks it skipped, so only a full run
    # can say a suppression excused nothing -- and only for checks that ran.
    if not args and not _config.FILE_FILTER:
        stale = _stale(script, suppressed, {k for k, n in counts.items() if n is not None}, keys)
        total += len(stale)
        _print("suppressions", f"every [suppress.{script}] entry still excuses something", stale, [])
    print(f"\n{total} finding(s)")
    return total


def _list(script, checks):
    for k, d, _ in checks:
        print(f"  {k:12} {d}{' (off)' if _config.disabled(script, k) else ''}")
    return 0


def _run_one(script, check, suppressed, vacuous, empty_why):
    """Run and print one check: its unsuppressed finding count, None when it
    did not run."""
    key, desc, fn = check
    result = _result(script, key, fn, vacuous, empty_why)
    if isinstance(result, Skip):
        print(f"--   {key:12} {desc}\n       · {result.why}")
        return None
    findings = _excused(suppressed, key, result[0])
    notes = list(result[1]) + [f"suppressed: {k} - {why}" for k, why in suppressed.used(key)]
    _print(key, desc, findings, notes)
    return len(findings)


def _selected(script, keys):
    """The checks named on the command line; none means all."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    unknown = [a for a in args if a not in keys]
    if unknown:
        # A misspelt check name used to select nothing and print 0 findings.
        raise SystemExit(f"unknown check(s) {', '.join(unknown)}; "
                         f"{script} has: {', '.join(keys)}")
    return args


def _result(script, key, fn, vacuous, empty_why):
    """The check's (findings, notes), or the Skip that stands in for it."""
    if _config.disabled(script, key):
        return Skip(f"turned off: [checks] off in {_config.FILENAME}")
    if vacuous:
        return Skip(empty_why)
    return fn()


def _excused(suppressed, check, findings):
    """The text of each finding no suppression of CHECK names."""
    return [f.text if isinstance(f, Finding) else f for f in findings
            if not (isinstance(f, Finding) and suppressed(check, f.key))]


def _print(key, desc, findings, notes):
    print(f"{'FAIL' if findings else 'ok  '} {key:12} {desc}")
    for n in notes:
        print(f"       · {n}")
    for f in findings:
        print(f"       ✗ {f}")


def _stale(script, suppressed, ran, keys):
    """Suppressions that excused nothing, and ones naming no check: a
    suppression that outlives what it excuses is a standing permission nobody
    remembers granting."""
    stale = [f"{check}: `{key}` excused nothing - the finding it covers is "
             f"gone, so the entry should be too"
             for check, key in suppressed.stale() if check in ran]
    return stale + [f"{check}: no such check in {script}"
                    for check in sorted(suppressed.checks() - set(keys))]


def exit_with(n):
    """Exit codes above 255 wrap; 250 caps the count without reaching 0."""
    sys.exit(min(n, 250))
