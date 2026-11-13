"""What make_ddic.py and make_meta.py share: the abapGit envelope, where an
object's file lives, and the write / `--check` bargain.

Both generators state their objects in a readable table and emit the XML;
`--check` regenerates into memory and reports what differs on disk. The two
copies of this code had already been fixed identically twice (`_path_for`,
`_reject_unknown_args`) -- the next fix lands here once.
"""

import sys

HEAD = ('<?xml version="1.0" encoding="utf-8"?>\n'
        '<abapGit version="v1.0.0" serializer="{ser}" serializer_version="v1.0.0">\n'
        ' <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">\n'
        '  <asx:values>\n')
TAIL = '  </asx:values>\n </asx:abap>\n</abapGit>\n'


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def path_for(name, root):
    """Where this object already lives, or the root if it is new.

    The package was split into subpackages after the generators were written
    and the output path stayed flat. `--check` therefore reported every moved
    object as drifted, and write mode duplicated it into src/ root beside the
    real one. Resolving by filename keeps the generators agnostic about the
    folder layout, which is abapGit's business and not theirs.

    The direct path wins before the search, because `package.devc.xml` is the
    one basename that is NOT unique -- every subpackage has one -- and rglob
    sorted `app/package.devc.xml` ahead of the root's.
    """
    direct = root / name
    if direct.exists():
        return direct
    hits = sorted(root.rglob(name))
    return hits[0] if hits else direct


def reject_unknown_args(doc):
    """An unrecognised argument must not fall through to write mode.

    `--check` was the only flag ever parsed, by `if "--check" in sys.argv`,
    so every other argument -- including `--help` -- meant "regenerate and
    overwrite". That is how a generator came to rewrite the package while
    someone was asking it what it does.
    """
    unknown = [a for a in sys.argv[1:] if a != "--check"]
    if unknown:
        print(doc.strip())
        print(f"\nunrecognised argument(s): {' '.join(unknown)}")
        sys.exit(2)


def check(files, root):
    """Print every generated file that differs from disk; return the count."""
    drift = [n for n, c in files.items()
             if not path_for(n, root).exists()
             or path_for(n, root).read_text() != c]
    for n in sorted(drift):
        print(f"  ✗ {n} differs from the definition")
    print(f"\n{len(files)} object(s), {len(drift)} drifted")
    return len(drift)


def write(files, root):
    root.mkdir(exist_ok=True)
    for name, content in files.items():
        path_for(name, root).write_text(content)
