"""The house prefixes: of types, by visibility, and of methods."""

import re

import _abap
from _config import get
from _runner import Finding, needs
from _standing.package import CODE, KINDS, SRC, main_class


TYPE_PUBLIC = get("naming.type_public", "mty_")
TYPE_PRIVATE = get("naming.type_private", "_mty_")
METHOD_PRIVATE = get("naming.method_private", "_")


def _type_declarations(name):
    """Every type NAME an object's main declaration part introduces, with its
    visibility: an interface's whole text is public, a class's sections are
    its own class's.

    Components are NOT type names. `_declared_names` sweeps them up because
    the qualified check wants the safe direction; here that would demand the
    type prefix of every field, so BEGIN OF / END OF depth is tracked across
    the statements and the members of a chain, and only depth 0 introduces a
    name.
    """
    if KINDS.get(name) == "intf":
        parts = [("PUBLIC", CODE[name])]
    else:
        cls = main_class(name)
        parts = [(vis, cls.section(vis)) for vis in ("PUBLIC", "PROTECTED", "PRIVATE")] \
            if cls else []
    return [(vis, typ) for vis, body in parts for typ in _type_names(body)]


def _type_names(body):
    """The names TYPES statements in BODY introduce at depth 0, in order: a
    structure's name, and every `name TYPE ...` outside one."""
    return [m.group(1) or m.group(2) for depth, part in _abap.chain_parts(body, "TYPES")
            if depth == 0 and (m := _TYPE_NAME.match(part))]


_TYPE_NAME = re.compile(r"(?i)BEGIN\s+OF\s+(\w+)|(\w+)\s+TYPE\b")


def check_typenames():
    """A declared type carries the public prefix where it is public, the
    private one where it is not.

    A convention that is only in people's heads is re-decided per object, and
    the divergence surfaces as an unresolvable member months later.

    A CLASS POOL'S LOCAL CLASSES ARE OUT OF SCOPE: local types are `lty_`, a
    different question. Only the main class definition is read. A program's
    local class is read: it is the program's own design, not a helper.
    """
    if not TYPE_PUBLIC or not TYPE_PRIVATE:
        return needs("[naming] type_public and type_private")
    want_of = {"PUBLIC": TYPE_PUBLIC, "PROTECTED": TYPE_PRIVATE, "PRIVATE": TYPE_PRIVATE}
    bad, n = [], 0
    for name, text in SRC.items():
        # A program's local class counts: it is the program's design.
        if KINDS.get(name) not in ("clas", "intf", "prog"):
            continue
        for vis, typ in _type_declarations(name):
            n += 1
            want = want_of[vis]
            if typ.lower().startswith(want):
                continue
            key = f"{name}: {typ} is {vis.lower()}, expected {want}*"
            bad.append(Finding(key, key))
    return sorted(set(bad)), [
        f"{n} type declaration(s) scanned",
        f"public = {TYPE_PUBLIC}, protected/private = {TYPE_PRIVATE}"]


def check_methodnames():
    """A method is bare where it is public, prefixed where it is not.

    The sibling of `typenames`, for the member abaplint's
    `class_attribute_names` does not reach.

    TEST CLASSES ARE OUT OF SCOPE and counted in the notes, as abaplint's
    `ignoreLocal` leaves their attributes: ABAP Unit wants them private, it
    is not a choice. A REDEFINITION keeps the name it redefines.
    """
    if not METHOD_PRIVATE:
        return needs("[naming] method_private")
    bad, n, skipped = [], 0, 0
    for name in SRC:
        for cls in _abap.class_definitions(CODE[name]):
            skipped += cls.for_testing
            methods = [] if cls.for_testing else list(_renamable_methods(cls))
            n += len(methods)
            keys = (_misnamed(f"{name}: {cls.name}", vis, method) for vis, method in methods)
            bad += [Finding(k, k) for k in keys if k]
    return sorted(set(bad)), [
        f"{n} method declaration(s) scanned, {skipped} test class(es) skipped",
        f"public = bare, protected/private = {METHOD_PRIVATE}"]


def _misnamed(owner, vis, method):
    """The finding for METHOD of OWNER when its prefix does not match VIS."""
    if method.lower().startswith(METHOD_PRIVATE) == (vis != "PUBLIC"):
        return None
    want = f"no {METHOD_PRIVATE}" if vis == "PUBLIC" else f"{METHOD_PRIVATE}*"
    return f"{owner}->{method} is {vis.lower()}, expected {want}"


def _renamable_methods(cls):
    """(visibility, method) for each method a class declares that may take
    any name: a REDEFINITION keeps its ancestor's name, and a constructor
    cannot have another."""
    for vis in ("PUBLIC", "PROTECTED", "PRIVATE"):
        for d in cls.methods(vis):
            if not d.is_redef and d.name.lower() not in ("constructor", "class_constructor"):
                yield vis, d.name
