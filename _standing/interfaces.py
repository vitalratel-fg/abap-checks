"""Interface methods: called, implemented, and their RAISING propagated."""

import re

import _abap
from _runner import Finding
from _standing.package import CLASSES, CODE, GLOBAL, INTERFACES, SRC, suppressed


def _caught_here(body, pos):
    """Is offset POS inside a TRY ... ENDTRY that declares a CATCH?

    Deliberately coarse: it does not match the exception class against the
    CATCH, so a TRY that catches something unrelated reads as handled. The
    alternative -- no TRY awareness at all -- reports every correctly handled
    call, which is how a check stops being read.
    """
    open_try, closed = [], []
    for m in re.finditer(r"\b(TRY|CATCH|ENDTRY)\b", body, re.I):
        word = m.group(1).upper()
        if word == "TRY":
            open_try.append([m.start(), False])
        elif word == "CATCH" and open_try:
            open_try[-1][1] = True
        elif word == "ENDTRY" and open_try:
            start, has_catch = open_try.pop()
            closed.append((start, m.end(), has_catch))
    return (any(has_catch and start < pos < end for start, end, has_catch in closed)
            or any(has_catch and start < pos for start, has_catch in open_try))


def check_raising():
    """A method that calls a raising interface method must declare RAISING.

    REDEFINITION IS NOT A DECLARATION. `METHODS x REDEFINITION.` carries the
    ancestor's signature -- ABAP forbids changing it -- so the RAISING clause
    lives in the base class, not in the file being scanned.

    HANDLING IS NOT PROPAGATING. Declaring RAISING is one of two valid
    answers; the other is TRY ... CATCH round the call.

    LIMIT: a call is recognised as `m*->meth(` / `_m*->meth(` on a member
    reference, the convention every package so far has used.
    """
    raises = {d.name.lower(): "RAISING" in d.sig.upper()
              for s in INTERFACES.values() for d in _abap.declarations(s)}
    declared = {}
    for d in (d for s in SRC.values() for d in _abap.declarations(s) if not d.is_redef):
        declared.setdefault(d.name.lower(), "RAISING" in d.sig.upper())
    bad = []
    for n, s in CLASSES.items():
        # Its own declarations, chains included: `METHODS: a, b.` declares b
        # as surely as `METHODS b.` does.
        own = {d.name.lower(): d for d in _abap.declarations(CODE[n]) if not d.is_redef}
        silent = {m for m, d in own.items() if "RAISING" not in d.sig.upper()
                  and not raises.get(m) and not declared.get(m)}
        bad += [Finding(f"{n}~{short}", f"{n}~{short}") for b in _abap.method_bodies(s)
                if (short := b.name.split("~")[-1].lower()) in silent
                and _raising_calls(b.body, raises)]
    return sorted(set(bad)), []


def _raising_calls(body, raises):
    """Calls in BODY of a raising interface method, outside a TRY that catches."""
    return [m for m in re.finditer(r"[m_][o0a]?_?\w*->(\w+)\s*\(", body)
            if raises.get(m.group(1).lower()) and not _caught_here(body, m.start())]


_REF_DECL = re.compile(r"(?im)^\s*(?:CLASS-)?DATA\s+(\w+)\s+TYPE\s+REF\s+TO\s+(\w+)")
_REF_PARAM = re.compile(r"(?i)!?(\w+)\s+TYPE\s+REF\s+TO\s+(\w+)")
_REF_NEW = re.compile(r"(?i)\bDATA\((\w+)\)\s*=\s*NEW\s+(\w+)\s*\(")

_CALL_QUAL = re.compile(r"(?i)(?:->)?(\w+)~(\w+)\s*\(")
_CALL_ARROW = re.compile(r"(?i)(\w*)\s*->\s*(\w+)\s*\(")
_CALL_BADI = re.compile(r"(?im)^\s*CALL\s+BADI\s+\w+->(\w+)\b")


def _ref_types(text):
    """Every reference variable in one object, mapped to its declared type."""
    types = {}
    for rx in (_REF_DECL, _REF_PARAM, _REF_NEW):
        for var, typ in rx.findall(text):
            types.setdefault(var.lower(), typ.lower())
    return types


def check_orphans():
    """An interface method nobody calls.

    KEYED ON INTERFACE~METHOD, NOT ON THE NAME ALONE. Matching the bare name
    lets one interface's callers satisfy another's declarations whenever the
    two share a method name -- normal for a pair of adapters by design.

    A call is attributed three ways, in order of certainty:
      ->IFACE~METH(   names its interface outright
      VAR->METH(      resolved through VAR's declared type
      unresolved      credited to every interface declaring METH

    The fallback keeps a false orphan from being reported when a reference is
    typed somewhere this cannot see. It is counted and reported, because a
    check that silently degrades is the failure this file exists to avoid.

    An interface the package implements for someone else to call (a BAdI, a
    framework callback) has no caller here by design: suppress it with that
    reason, `iface.method`.
    """
    iface_methods = {n: {m.lower() for m in _abap.interface_methods(s)}
                     for n, s in INTERFACES.items()}
    implements = {n: list(c.interfaces()) for n, c in GLOBAL.items()}
    called, by_name = _calls(iface_methods, implements)
    # Consulted here, not by the runner: a suppressed method must not then
    # count as credited by name in the note below.
    uncalled = [(i, m) for i, methods in iface_methods.items() for m in sorted(methods)
                if (i, m) not in called and not suppressed("orphans", f"{i}.{m}")]
    bad = sorted(f"{i}.{m}" for i, m in uncalled if not by_name.get(m, set()) - {i})
    guessed = len(uncalled) - len(bad)
    return bad, [f"{guessed} method(s) credited by NAME only - the reference "
                 f"could not be typed from this package"] if guessed else []


def _calls(iface_methods, implements):
    """({(interface, method)} the package calls, {method: callers} of calls
    whose interface could not be told)."""
    called, by_name = set(), {}
    for caller, text in SRC.items():
        typed, unresolved = _arrow_calls(text, iface_methods, implements)
        called |= typed | {(i.lower(), m.lower()) for i, m in _CALL_QUAL.findall(text)}
        # CALL BADI badi->meth has no parenthesis, and the handle's type is
        # the BAdI, not its interface: credited by name.
        for meth in unresolved + [m.lower() for m in _CALL_BADI.findall(CODE[caller])]:
            by_name.setdefault(meth, set()).add(caller)
    return called, by_name


def _arrow_calls(text, iface_methods, implements):
    """({(interface, method)} the `var->meth(` calls in TEXT reach through
    var's declared type, [methods] of the calls whose var it cannot type)."""
    types, called, unresolved = _ref_types(text), set(), []
    for var, meth in _CALL_ARROW.findall(text):
        targets = _call_targets(types.get(var.lower()) if var else None, meth.lower(),
                                iface_methods, implements)
        if targets is None:
            unresolved.append(meth.lower())
        else:
            called |= targets
    return called, unresolved


def _call_targets(typ, meth, iface_methods, implements):
    """{(interface, method)} a call of METH on a reference of type TYP reaches,
    or None when TYP is neither an interface nor a class of this package."""
    if typ in iface_methods:
        return {(typ, meth)}
    if typ in implements:
        return {(i, meth) for i in implements[typ] if meth in iface_methods.get(i, ())}
    return None


def check_impls():
    """An interface method with no implementation anywhere in a class's line.

    The mirror of `orphans`. That one finds a method nobody CALLS; this one a
    method nobody WRITES, which is the worse half: an uncalled declaration is
    dead surface, an unimplemented one does not compile.

    THREE THINGS IT MUST GET RIGHT, each a false alarm otherwise:
      inheritance      the INTERFACES statement may sit on an ancestor
      ABSTRACT METHODS `INTERFACES i ABSTRACT METHODS m.` defers M, so the
                       base is right not to implement it and every concrete
                       descendant must
      abstract class   a deferred method is a finding on concrete
                       descendants, never on the abstract base

    Only interfaces of this package are checked: an SAP interface's methods
    are not on disk to compare against.

    LIMITS: ALIASES are not handled; a commented-out implementation does not
    count, which is the right way round because the question is whether it
    compiles.
    """
    ifaces = {n: [m.lower() for m in _abap.interface_methods(s)] for n, s in INTERFACES.items()}
    bad, contracts = [], 0
    for cls in sorted(GLOBAL):
        required, deferred = _contracts(cls, ifaces)
        contracts += len(set(required.values()))
        bad += _owed(cls, required, deferred)
    abstract = sorted(n for n, c in GLOBAL.items() if c.abstract)
    return bad, [f"{len(CLASSES)} classes, {contracts} interface contract(s)",
                 f"abstract, deferral honoured: {abstract}"]


def _owed(cls, required, deferred):
    """A finding for each required method nothing in CLS's line implements;
    an abstract class may leave the deferred ones to its descendants."""
    supplied = {m.lower() for a in _ancestry(cls) for m in _implemented(a)}
    owed = [k for k in sorted(required) if k not in supplied
            and not (GLOBAL[cls].abstract and k in deferred)]
    why = "  (deferred by an ancestor - this concrete class owes it)"
    return [Finding(f"{cls}: {k}{why if k in deferred else ''}", f"{cls}.{k}") for k in owed]


def _ancestry(cls):
    """CLS and its ancestors on disk, nearest first."""
    out = []
    while cls in GLOBAL and cls not in out:
        out.append(cls)
        cls = GLOBAL[cls].parent
    return out


def _implemented(cls):
    """`iface~method` names the class's own implementation part implements."""
    return _abap.implemented_methods(_abap.class_implementation(CODE[cls], cls))


def _contracts(cls, ifaces):
    """({`iface~method`: iface} CLS owes for this package's interfaces it or an
    ancestor declares, {`iface~method`} an ancestor deferred as ABSTRACT)."""
    required, deferred = {}, set()
    for a in _ancestry(cls):
        for iface, defer in GLOBAL[a].interfaces().items():
            methods = ifaces.get(iface)
            if methods is None:
                continue
            required.update({f"{iface}~{m}": iface for m in methods})
            deferred |= {f"{iface}~{m.lower()}" for m in (methods if defer == _abap.ALL else defer)}
    return required, deferred
