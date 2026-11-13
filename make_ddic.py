#!/usr/bin/env python3
"""Emit the package's DDIC as abapGit XML, from one readable definition.

    python3 make_ddic.py            # write *.doma.xml, *.dtel.xml, *.tabl.xml, *.enqu.xml
    python3 make_ddic.py --check    # regenerate into memory and report differences

WHY A GENERATOR
---------------
Forty XML files stating eight domains, twenty-three data elements and nine
tables is forty places for a ROLLNAME to be mistyped, and the mistake does not
surface until abapGit fails the import naming the table rather than the missing
element. Here the field list IS the definition: a data element can only be used
if it is defined here or is a standard one with a known type, and `--check`
proves the XML on disk still matches.

BOOTSTRAP, NOT A ROUND TRIP. Once the package is imported, SE11 is where DDIC
is maintained and abapGit's own serialisation is authoritative. Run `--check`
after a pull to see whether the two have diverged, and move the definition
here when it has.

THE DEFINITION (abapcheck.toml)
  [[ddic.domain]]   name, type, length, text, values = [[value, text], ...]
                    A domain exists only where fixed values carry meaning.
  [[ddic.element]]  name, domain = "ZX" | type = ["CURR", 11, 5],
                    short, medium, long
  [[ddic.table]]    name, delivery ("A" | "C"), text,
                    fields = [[field, rollname, key, reference field?], ...],
                    indexes = [[name, [fields], unique], ...]
  [[ddic.lock]]     name, table, mode, args = [fields]
  [ddic.standard]   NAME = [datatype, length, decimals]: SAP data elements
                    beyond _sap.STANDARD that a table uses

NO STANDARD DOMAINS: a standard domain adds nothing a predefined type does
not, and it makes the package depend on DDIC that abaplint cannot resolve --
it bundles no SAP standard objects, so a single unresolvable reference aborts
the parse of the whole table.
"""

import sys

import _gen
import _sap
from _config import ROOT, get
from _gen import HEAD, TAIL, esc

DOMAINS = [(d["name"], d["type"], d["length"], d["text"], [tuple(v) for v in d.get("values", [])])
           for d in get("ddic.domain", [])]
DATA_ELEMENTS = [(e["name"], tuple(e["type"]) if "type" in e else e["domain"],
                  e["short"], e["medium"], e["long"]) for e in get("ddic.element", [])]
TABLES = [(t["name"], t["delivery"], t["text"], [tuple(f) for f in t["fields"]],
           [tuple(i) for i in t.get("indexes", [])]) for t in get("ddic.table", [])]
LOCKS = [(k["name"], k["table"], k["mode"], list(k["args"])) for k in get("ddic.lock", [])]
STANDARD = {**_sap.STANDARD, **{k.upper(): tuple(v) for k, v in get("ddic.standard", {}).items()}}

# Delivery class -> data class.
DATA_CLASS = {"A": "APPL1", "C": "APPL2"}


def doma(name, datatype, length, text, values):
    out = [HEAD.format(ser="LCL_OBJECT_DOMA"), "   <DD01V>\n",
           f"    <DOMNAME>{name}</DOMNAME>\n", "    <DDLANGUAGE>E</DDLANGUAGE>\n",
           f"    <DATATYPE>{datatype}</DATATYPE>\n",
           f"    <LENG>{length:06d}</LENG>\n",
           f"    <OUTPUTLEN>{length:06d}</OUTPUTLEN>\n"]
    if values:
        out.append("    <VALEXI>X</VALEXI>\n")
    out += [f"    <DDTEXT>{esc(text)}</DDTEXT>\n", "   </DD01V>\n"]
    if values:
        out.append("   <DD07V_TAB>\n")
        for pos, (value, vtext) in enumerate(values, 1):
            out += ["    <DD07V>\n", f"     <VALPOS>{pos:04d}</VALPOS>\n",
                    "     <DDLANGUAGE>E</DDLANGUAGE>\n",
                    f"     <DOMVALUE_L>{value}</DOMVALUE_L>\n",
                    f"     <DDTEXT>{esc(vtext)}</DDTEXT>\n", "    </DD07V>\n"]
        out.append("   </DD07V_TAB>\n")
    return "".join(out) + TAIL


def dtel(name, kind, short, medium, long_):
    if isinstance(kind, tuple):
        datatype, length, decimals = (kind + (0,))[:3]
        typing = (f"    <DATATYPE>{datatype}</DATATYPE>\n"
                  f"    <LENG>{length:06d}</LENG>\n"
                  f"    <OUTPUTLEN>{length + (decimals > 0) * 2:06d}</OUTPUTLEN>\n"
                  f"    <DECIMALS>{decimals:06d}</DECIMALS>\n")
    else:
        domain = next(d for d in DOMAINS if d[0] == kind)
        typing = (f"    <DOMNAME>{kind}</DOMNAME>\n"
                  f"    <DATATYPE>{domain[1]}</DATATYPE>\n"
                  f"    <LENG>{domain[2]:06d}</LENG>\n"
                  f"    <OUTPUTLEN>{domain[2]:06d}</OUTPUTLEN>\n"
                  "    <DECIMALS>000000</DECIMALS>\n")
    return "".join([
        HEAD.format(ser="LCL_OBJECT_DTEL"), "   <DD04V>\n",
        f"    <ROLLNAME>{name}</ROLLNAME>\n", "    <DDLANGUAGE>E</DDLANGUAGE>\n",
        typing, "    <HEADLEN>20</HEADLEN>\n",
        "    <SCRLEN1>10</SCRLEN1>\n", "    <SCRLEN2>20</SCRLEN2>\n",
        "    <SCRLEN3>40</SCRLEN3>\n", f"    <DDTEXT>{esc(long_)}</DDTEXT>\n",
        f"    <REPTEXT>{esc(short)}</REPTEXT>\n",
        f"    <SCRTEXT_S>{esc(short)}</SCRTEXT_S>\n",
        f"    <SCRTEXT_M>{esc(medium)}</SCRTEXT_M>\n",
        f"    <SCRTEXT_L>{esc(long_)}</SCRTEXT_L>\n", "   </DD04V>\n", TAIL])


def _field_type(rollname, zdtel):
    """(datatype, length, decimals) for a field, standard or this package's;
    None for an element on a domain not defined here."""
    if rollname in STANDARD:
        return STANDARD[rollname]
    kind = zdtel[rollname]
    if isinstance(kind, tuple):
        return (kind + (0,))[:3]
    domain = next((d for d in DOMAINS if d[0] == kind), None)
    return (domain[1], domain[2], 0) if domain else None


def tabl(name, delivery, text, fields, indexes):
    out = [HEAD.format(ser="LCL_OBJECT_TABL"), "   <DD02V>\n",
           f"    <TABNAME>{name}</TABNAME>\n", "    <DDLANGUAGE>E</DDLANGUAGE>\n",
           "    <TABCLASS>TRANSP</TABCLASS>\n", "    <CLIDEP>X</CLIDEP>\n",
           f"    <DDTEXT>{esc(text)}</DDTEXT>\n",
           f"    <CONTFLAG>{delivery}</CONTFLAG>\n", "    <EXCLASS>1</EXCLASS>\n",
           "   </DD02V>\n", "   <DD09L>\n",
           f"    <TABNAME>{name}</TABNAME>\n", "    <AS4LOCAL>A</AS4LOCAL>\n",
           "    <TABKAT>0</TABKAT>\n",
           f"    <TABART>{DATA_CLASS[delivery]}</TABART>\n",
           "    <BUFALLOW>N</BUFALLOW>\n", "   </DD09L>\n", "   <DD03P_TABLE>\n"]
    out += [line for f in fields for line in _field_xml(name, *f)]
    out.append("   </DD03P_TABLE>\n")
    if indexes:
        out += ["   <DD12V>\n", *(line for i in indexes for line in _index_xml(name, *i)),
                "   </DD12V>\n   <DD17V>\n",
                *(line for idx, fs, _ in indexes for pos, f in enumerate(fs, 1)
                  for line in _index_field_xml(name, idx, pos, f)),
                "   </DD17V>\n"]
    return "".join(out) + TAIL


def _field_xml(table, field, rollname, key, *ref):
    datatype, length, decimals = _field_type(rollname, {d[0]: d[1] for d in DATA_ELEMENTS})
    out = ["    <DD03P>\n", f"     <FIELDNAME>{field}</FIELDNAME>\n"]
    if key:
        out += ["     <KEYFLAG>X</KEYFLAG>\n", "     <NOTNULL>X</NOTNULL>\n"]
    out += [f"     <ROLLNAME>{rollname}</ROLLNAME>\n",
            f"     <DATATYPE>{datatype}</DATATYPE>\n",
            f"     <LENG>{length:06d}</LENG>\n",
            f"     <DECIMALS>{decimals:06d}</DECIMALS>\n"]
    if ref:
        # A CURR field names its CUKY, a QUAN its UNIT: the system refuses either without.
        out += [f"     <REFTABLE>{table}</REFTABLE>\n", f"     <REFFIELD>{ref[0]}</REFFIELD>\n"]
    return out + ["    </DD03P>\n"]


def _index_xml(table, idx, _fields, unique):
    return ["    <DD12V>\n", f"     <SQLTAB>{table}</SQLTAB>\n",
            f"     <INDEXNAME>{idx}</INDEXNAME>\n",
            "     <DDLANGUAGE>E</DDLANGUAGE>\n",
            f"     <UNIQUEFLAG>{'X' if unique else ''}</UNIQUEFLAG>\n",
            f"     <DDTEXT>{esc(table)} index {idx}</DDTEXT>\n",
            "    </DD12V>\n"]


def _index_field_xml(table, idx, pos, field):
    return ["    <DD17V>\n", f"     <SQLTAB>{table}</SQLTAB>\n",
            f"     <INDEXNAME>{idx}</INDEXNAME>\n",
            f"     <POSITION>{pos:04d}</POSITION>\n",
            f"     <FIELDNAME>{field}</FIELDNAME>\n", "    </DD17V>\n"]


def enqu(name, table, mode, args):
    out = [HEAD.format(ser="LCL_OBJECT_ENQU"), "   <DD25V>\n",
           f"    <VIEWNAME>{name}</VIEWNAME>\n", "    <AGGTYPE>E</AGGTYPE>\n",
           f"    <ROOTTAB>{table}</ROOTTAB>\n", "    <DDLANGUAGE>E</DDLANGUAGE>\n",
           f"    <DDTEXT>Lock on {esc(table)}</DDTEXT>\n", "   </DD25V>\n",
           "   <DD26E_TABLE>\n", "    <DD26E>\n",
           f"     <VIEWNAME>{name}</VIEWNAME>\n", f"     <TABNAME>{table}</TABNAME>\n",
           "     <TABPOS>0001</TABPOS>\n", f"     <FORTABNAME>{table}</FORTABNAME>\n",
           f"     <ENQMODE>{mode}</ENQMODE>\n", "    </DD26E>\n",
           "   </DD26E_TABLE>\n", "   <DD27P_TABLE>\n"]
    for pos, field in enumerate(args, 1):
        out += ["    <DD27P>\n", f"     <VIEWNAME>{name}</VIEWNAME>\n",
                f"     <OBJPOS>{pos:04d}</OBJPOS>\n",
                f"     <VIEWFIELD>{field}</VIEWFIELD>\n",
                f"     <TABNAME>{table}</TABNAME>\n",
                f"     <FIELDNAME>{field}</FIELDNAME>\n",
                "     <KEYFLAG>X</KEYFLAG>\n", "    </DD27P>\n"]
    out.append("   </DD27P_TABLE>\n")
    return "".join(out) + TAIL


def generate():
    """{filename: content} for every DDIC object."""
    files = {}
    for name, datatype, length, text, values in DOMAINS:
        files[f"{name.lower()}.doma.xml"] = doma(name, datatype, length, text, values)
    for name, domain, short, medium, long_ in DATA_ELEMENTS:
        files[f"{name.lower()}.dtel.xml"] = dtel(name, domain, short, medium, long_)
    for name, delivery, text, fields, indexes in TABLES:
        files[f"{name.lower()}.tabl.xml"] = tabl(name, delivery, text, fields, indexes)
    for name, table, mode, args in LOCKS:
        files[f"{name.lower()}.enqu.xml"] = enqu(name, table, mode, args)
    return files


def validate():
    """Findings that would otherwise surface as a failed abapGit import."""
    return [error for rule in (_element_errors, _table_errors, _lock_errors) for error in rule()]


def _element_errors():
    domains = {d[0] for d in DOMAINS}
    bad = []
    for name, kind, *_ in DATA_ELEMENTS:
        if isinstance(kind, str) and kind not in domains:
            bad.append(f"{name}: domain {kind} is not defined here -- a "
                       f"standard domain makes the element unresolvable "
                       f"offline; use a predefined type instead")
        if len(name) > 30:
            bad.append(f"{name}: {len(name)} characters, limit is 30")
    return bad


def _table_errors():
    bad = []
    for name, delivery, _, fields, indexes in TABLES:
        if len(name) > 16:
            bad.append(f"{name}: {len(name)} characters, DDIC table limit is 16")
        if delivery not in DATA_CLASS:
            bad.append(f"{name}: delivery class {delivery} has no data class "
                       f"in DATA_CLASS")
        bad += _field_errors(name, fields) + _index_errors(name, fields, indexes)
    return bad


def _field_errors(name, fields):
    """Each field's element resolves offline, and an amount or quantity names
    a currency or unit field of the same table."""
    elements = {d[0] for d in DATA_ELEMENTS}
    types = {f[0]: _datatype(f[1]) for f in fields}
    bad = []
    for field, rollname, _, *ref in fields:
        need = {"CURR": "CUKY", "QUAN": "UNIT"}.get(types[field])
        if need and not ref:
            bad.append(f"{name}-{field}: {types[field]} without a reference field")
        if ref and types.get(ref[0]) != need:
            bad.append(f"{name}-{field}: reference {ref[0]} is not a {need} field")
        if rollname not in elements and rollname not in STANDARD:
            bad.append(f"{name}-{field}: {rollname} is neither defined here nor a "
                       f"standard element with a type in [ddic.standard], so "
                       f"the field cannot be parsed without the SAP system")
    return bad


def _index_errors(name, fields, indexes):
    names = {f[0] for f in fields}
    bad = []
    for idx, idx_fields, _ in indexes:
        if len(idx) != 3:
            bad.append(f"{name}~{idx}: an index name is exactly 3 characters")
        bad += [f"{name}~{idx}: no field {f}" for f in idx_fields if f not in names]
    return bad


def _lock_errors():
    tables = {t[0]: {f[0] for f in t[3]} for t in TABLES}
    bad = []
    for name, table, _, args in LOCKS:
        if table not in tables:
            bad.append(f"{name}: primary table {table} is not defined here")
        else:
            bad += [f"{name}: {table} has no field {a}" for a in args if a not in tables[table]]
    return bad


def _datatype(rollname):
    """The DDIC type of an element, or None when it does not resolve here: an
    unknown element, or one on a domain this package does not define (both
    reported on their own -- validating must not fail on what it reports)."""
    zdtel = {d[0]: d[1] for d in DATA_ELEMENTS}
    if rollname not in STANDARD and rollname not in zdtel:
        return None
    return (_field_type(rollname, zdtel) or (None,))[0]


def main():
    _gen.reject_unknown_args(__doc__)
    if not (DOMAINS or DATA_ELEMENTS or TABLES or LOCKS):
        print("--  no [ddic] definition in abapcheck.toml: nothing to generate")
        return 0
    bad = validate()
    for line in bad:
        print(f"  ✗ {line}")
    if bad:
        print(f"\n{len(bad)} definition error(s) -- nothing written")
        return len(bad)

    files = generate()
    if "--check" in sys.argv:
        return _gen.check(files, ROOT)

    _gen.write(files, ROOT)
    print(f"{len(DOMAINS)} domain(s), {len(DATA_ELEMENTS)} data element(s), "
          f"{len(TABLES)} table(s), {len(LOCKS)} lock object(s) "
          f"-> {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(min(main(), 250))
