# abap-checks

Static checks for ABAP and CDS packages kept in git in abapGit layout. They find what compiles perfectly and is still wrong. Python 3.11+, standard library only, nothing to install. Every script's exit code is its finding count, so any of them works as a hook or a CI gate.

They grew in three packages (a ZMQU refactor, an MDG workflow and a CDS report rebuild) and were copied, retargeted and fixed separately in each. This is the one copy: the scripts know nothing about any project, and each project describes itself in an `abapcheck.toml`.

```bash
# from a project's root (the config is found by walking up, like abaplint.json)
uv run --no-project python ~/Documents/abap-checks/check_all.py
uv run --no-project python ~/Documents/abap-checks/check_standing.py orphans impls
uv run --no-project python ~/Documents/abap-checks/check_cds.py --list

# another project, or a config kept elsewhere
python3 check_all.py --project ../other
python3 check_all.py --config cmo/abapcheck.toml   # one repo, two packages
```

Wired into a project's `package.json`:

```json
"checks": "uv run --no-project python ~/Documents/abap-checks/check_all.py",
"verify": "bun run checks; c=$?; bun run lint; exit $((c + $?))"
```

## What each script answers

| Script | Question |
|---|---|
| `check_standing.py` | ABAP hygiene in any package: acyclic interface graph, RAISING propagation, `=>member` resolves, name lengths, type and method prefixes, interface methods nobody calls or implements, dead private methods, write-only fields, `LOOP … INTO`, dead constants, DDIC references on disk, retired names. |
| `check_design.py` | Agreements about the package's tables and reports: one table, one owner; every column read and every application column written; every fixed value a table can hold is assigned somewhere; report event blocks only declare, construct and call; the object register and disk are the same set. |
| `check_cds.py` | 30 CDS rules: view entities only, no DISTINCT / OR-joins / self-comparisons, stated cardinality that binds the whole key, access controls that grant on their own view, CASE with ELSE, keys first, filter fields that are plain columns, a data-source budget. |
| `check_app.py` | Fiori elements V4 apps under `ui/`: every name the manifest uses resolves against the service definition and the metadata extensions. |
| `check_luw.py` | Only the owners commit; nothing in a caller's LUW calls an API that commits by default; a LUW chosen by the assembler reaches every collaborator. |
| `check_messages.py` | Every T100 number raised is defined, raised once per arity, with the right number of `&` slots; a message buffer is injected or returned, never both, and nothing returns above its export. |
| `check_sorted_rows.py` | No write through a row its SORTED / HASHED / FINAL table protects: the dump `MOVE_TO_LIT_NOTALLOWED_NODATA` before it happens. |
| `check_bare_bool.py` | `IF is_x( ).`: a functional call used as a condition. A syntax error, not style. |
| `check_clobbered_writes.py` | A field written, then discarded by a wholesale assignment to its structure. |
| `check_model_writers.py` | Every field of the model interface's structures has a writer. |
| `check_stubs.py` | A report, not a gate: which methods are empty, which are blocked on an open point, and which are both. `--md` groups them by open point. |
| `make_ddic.py`, `make_meta.py` | Emit DDIC and class/interface/program/message-class XML from `[ddic]` / `[meta]`; `--check` reports drift from disk. |
| `cds_sources.py` | A measurement: how many data-source references a view drags into a statement, expanded through views and AMDP bodies. |
| `check_all.py` | Every gate, one exit code (the number of scripts that failed). `--with stubs` adds the report. |

The two largest keep their rules in a package beside them: `_cds_rules/` (statement shape, joins, access control, consumption views, project facts) and `_standing/` (references, naming, interfaces, dead code, and the package model they share). The script stays the entry point and its header documents every rule, in the order it runs them.

## Three marks, never two

```
ok   orphans      interface method with no caller
FAIL loops        LOOP AT ... ASSIGNING, not INTO
       ✗ zcl_x: LOOP AT lt_rows INTO - use ASSIGNING FIELD-SYMBOL
--   renamed      retired identifiers still live
       · not configured: set `[naming] retired` in abapcheck.toml
```

`--` means the check ran on nothing: no source, a convention turned off, or a fact the config does not state. A check that scanned nothing printing `ok` is the failure this suite was built to stop. It happened five times before the rule existed: a regex that parsed no structures, prefixes that matched no objects, a grep with `\d` in ERE.

## Three kinds of check

| Kind | On when | Examples |
|---|---|---|
| defect | always | `impls`, `qualified`, `ddic`, `barebool`, `keyedrows`, `missing`, `selfcmp`, `toone` |
| convention | by default; `[checks] off` turns one off | `typenames`, `methodnames`, `loops`, `owners`, `eventblocks`, `commit`, `cds.distinct` |
| fact | when its key is set | `renamed`, `undrafted`, `register`, `sync`, `inject`, `buffer`, `cds.budget`, `cds.mandatory`, `unwritten` |

`abapcheck.example.toml` lists every key with a comment. Object kinds come from file suffixes (`.clas.abap`, `.intf.abap`), never from a name prefix. The source root comes from `.abapgit.xml` unless `[package] root` says otherwise.

## Suppressions

A known-good finding is excused in the config, keyed by the exact text the check reports, with the reason someone looked:

```toml
[suppress.standing.orphans]
"zif_x_badi.execute" = "called by the BAdI framework, not by this package"
```

Every check prints what it suppressed beside its result. On a full run, an entry that excused nothing is a finding of its own, and so is an entry for a check that does not exist. A suppression that outlives what it excuses is a standing permission nobody remembers granting.

## Project-specific checks stay in the project

A check that reads a project's own documents, such as a traceability table or a build plan's step numbers, belongs in that project's `tools/`. It can still use this suite's reader, lexers and runner:

```python
import sys; sys.path.insert(0, "/home/cpru/Documents/abap-checks")
from _config import get          # its own keys: [trace] file = ...
from _pkg import abap_by_stem, docs
from _runner import run, suppressions
```

## Proving the checks

`tests/` builds a throwaway project per test and asserts that each check fires on the defect it exists for and stays silent next to it. A rule that matches nothing reads exactly like a rule that works, and this is what tells them apart. There is one module per script (`test_standing.py`, `test_cds.py`, ...); a project too large to read inline is a folder under `tests/fixtures/`, which the tests copy and which every script can be run on by hand.

```bash
uv run --no-project python -m unittest discover -s tests          # all
uv run --no-project python -m unittest discover -s tests -p test_luw.py   # one script's
```

A change to a lexer (`_abap.py`, `_cds.py`) or to the reader (`_pkg.py`) is tested here first. A form the lexer misses is fixed in the lexer, never with a local regex in a check: a local regex is how one package came to have eleven disagreeing versions of "find a method".
