#!/usr/bin/env python3
"""The UI5 apps of the package, checked against the service they run on.

    python3 check_app.py
    python3 check_app.py views routing   # named checks only
    python3 check_app.py --list

Exit code is the number of findings, so it is usable in a hook.

WHY THIS EXISTS
---------------
A Fiori elements app is a manifest that names things in the service: entity
sets, associations, annotation qualifiers, routes. A name that does not
resolve fails silently at runtime -- a tab with no table, a row that does not
navigate, a table that keeps the default type -- and only in the browser,
after an upload. Every name the manifest uses is checked here against the
service definition and the metadata extensions on disk.

An app is a folder under `[package] ui` (default `ui/`) holding a
manifest.json: one BSP application, the folder /UI5/UI5_REPOSITORY_LOAD
uploads.

WHAT IT CHECKS
--------------
  service   the data source is the OData V4 URL of a service binding, its
            service definition is on disk, and (with [register] file) the
            binding is in the register
  entities  every contextPath and view entity set is exposed; every
            association in a path is one the view defines
  views     every view's annotationPath (SelectionVariant#Q and kin) is
            annotated in that entity's metadata extension
  tables    every table in controlConfiguration has a @UI.lineItem; with
            [app] table_type, every table is that type (SAP: do not mix
            table types across views)
  routing   every navigation names a route, every route a target, every
            target is reached
  load      ([app] initial_load) every List Report has that initialLoad
  ids       app id, Component name, i18n bundle and index.html resource
            root agree; the folder is a BSP name of at most 15 characters
            (and in the register, with [register] file); with [app]
            max_ui5, minUI5Version is at most the system's

WHAT IT CANNOT SEE
------------------
Whether Fiori elements accepts the settings: names resolve here, behaviour
is seen in the browser.
"""

import json
import re

from _cds import strip_comments
from _config import get, path
from _pkg import apps, cds_files
from _runner import Finding, exit_with, needs, run, suppressions

SCRIPT = "app"
suppressed = suppressions(SCRIPT)

_max_ui5 = get("app.max_ui5")
SYSTEM_UI5 = tuple(int(x) for x in _max_ui5.split(".")[:2]) if _max_ui5 else None
TABLE_TYPE = get("app.table_type")
INITIAL_LOAD = get("app.initial_load")
BSP_NAME_MAX = 15
V4_URL = re.compile(r"^/sap/opu/odata4/sap/(\w+)/srvd/sap/(\w+)/(\d{4})/$")
# Manifest annotation terms -> the CDS annotation that produces them.
TERMS = {"SelectionVariant": "selectionVariant",
         "SelectionPresentationVariant": "selectionPresentationVariant",
         "PresentationVariant": "presentationVariant",
         "LineItem": "lineItem"}


class App:
    """One app and the service objects its manifest names."""

    def __init__(self, name, folder):
        self.name, self.folder = name, folder
        self.manifest = json.loads((folder / "manifest.json").read_text())
        self.ui5 = self.manifest.get("sap.ui5", {})
        self.targets = self.ui5.get("routing", {}).get("targets", {})
        uri = self.manifest.get("sap.app", {}).get("dataSources", {}) \
            .get("mainService", {}).get("uri", "")
        m = V4_URL.match(uri)
        self.uri, self.binding, self.srvd = uri, m and m.group(1), m and m.group(2)
        srvd = cds_files("srvd").get(self.srvd or "", "")
        # Entity set name -> the CDS entity it exposes.
        self.sets = {alias: view.lower() for view, alias in
                     re.findall(r"\bexpose\s+(\w+)\s+as\s+(\w+)", strip_comments(srvd), re.I)}
        self.ddls, self.ddlx = cds_files("ddls"), cds_files("ddlx")

    def entity(self, path):
        """The CDS entity at a path like `/Reclass/_Basis`, or a finding."""
        parts = [p for p in path.split("/") if p]
        if not parts or parts[0] not in self.sets:
            return None, f"{path}: entity set {parts[0] if parts else '?'} is not exposed by {self.srvd}"
        view = self.sets[parts[0]]
        for assoc in parts[1:]:
            m = re.search(rf"\bassociation\b[^\n]*?\b(\w+)\s+as\s+{assoc}\b",
                          strip_comments(self.ddls.get(view, "")), re.I)
            if not m:
                return None, f"{path}: {view.upper()} defines no association {assoc}"
            view = m.group(1).lower()
        return view, None

    def annotated(self, view, term, qualifier):
        """True if the view's metadata extension carries @UI.<term> with that qualifier."""
        cds = TERMS.get(term)
        src = strip_comments(self.ddlx.get(view, ""))
        hits = re.findall(rf"@UI\.{cds}\s*:\s*\[(.*?)\]", src, re.S | re.I) if cds else []
        if qualifier is None:
            return bool(hits) or bool(re.search(rf"@UI\.{cds}\s*:\s*\{{", src, re.I))
        return any(re.search(rf"\bqualifier\s*:\s*'{qualifier}'", h) for h in hits)

    def list_reports(self):
        return {k: t for k, t in self.targets.items() if t.get("name") == "sap.fe.templates.ListReport"}

    def settings(self, target):
        return target.get("options", {}).get("settings", {})


def check_service(app, register):
    bad = []
    if not app.binding:
        return [f"{app.uri or 'no mainService uri'}: not an OData V4 service-binding URL"]
    if register is not None and f"`{app.binding.upper()}`" not in register:
        bad.append(f"binding {app.binding.upper()} is not in the object register")
    if not app.sets:
        bad.append(f"service definition {app.srvd.upper()} not on disk, or exposes nothing")
    ds = app.manifest["sap.app"]["dataSources"]["mainService"]
    if ds.get("settings", {}).get("odataVersion") != "4.0":
        bad.append("mainService is not odataVersion 4.0")
    return bad


def check_entities(app, register):
    bad = []
    for key, t in app.targets.items():
        s = app.settings(t)
        paths = [s.get("contextPath", "")] + [
            "/" + v["entitySet"] for v in s.get("views", {}).get("paths", []) if "entitySet" in v]
        for p in paths:
            _, err = app.entity(p)
            if err:
                bad.append(f"{key}: {err}")
    return bad


def _annotation_path(path):
    """`com.sap.vocabularies.UI.v1.SelectionVariant#Tab` -> ('SelectionVariant', 'Tab')."""
    m = re.match(r"com\.sap\.vocabularies\.UI\.v1\.(\w+)(?:#(\w+))?$", path)
    return (m.group(1), m.group(2)) if m else (None, None)


def check_views(app, register):
    return [f"{key}/{v.get('key')}: {why}" for key, t in app.list_reports().items()
            for v in app.settings(t).get("views", {}).get("paths", [])
            if (why := _view_problem(app, v, app.settings(t).get("contextPath", "")))]


def _view_problem(app, v, main):
    """Why one view of a List Report names an annotation its entity lacks, or
    None. A view whose entity does not resolve is `entities`' finding."""
    view, err = app.entity("/" + v["entitySet"] if "entitySet" in v else main)
    if err:
        return None
    term, qual = _annotation_path(v.get("annotationPath", ""))
    if term not in TERMS:
        return f"annotationPath {v.get('annotationPath')} is not a UI variant or line item"
    if not app.annotated(view, term, qual):
        return f"{view.upper()} has no @UI.{TERMS[term]}" + (f" qualifier '{qual}'" if qual else "")
    return None


def check_tables(app, register):
    return [f"{key}: {why}" for key, t in app.targets.items()
            for ckey, conf in app.settings(t).get("controlConfiguration", {}).items()
            for why in _table_problems(app, app.settings(t), ckey, conf)]


def _table_problems(app, settings, ckey, conf):
    """What is wrong with one controlConfiguration entry: a key not understood,
    an entity that does not resolve, a table without its line item, or a
    table of another type than [app] table_type."""
    m = re.match(r"^(/\w+/)?((?:_\w+/)*)@(.+)$", ckey)
    if not m:
        return [f"controlConfiguration key {ckey} not understood"]
    base = m.group(1) or settings.get("contextPath", "")
    view, err = app.entity(base.rstrip("/") + "/" + m.group(2).rstrip("/"))
    term, qual = _annotation_path(m.group(3))
    bad = [err] if err else []
    if not err and term == "LineItem" and not app.annotated(view, term, qual):
        bad.append(f"{ckey}: {view.upper()} has no @UI.lineItem")
    kind = conf.get("tableSettings", {}).get("type")
    if TABLE_TYPE and term == "LineItem" and kind != TABLE_TYPE:
        bad.append(f"{ckey} is {kind or 'the default table'}, not {TABLE_TYPE}")
    return bad


def check_routing(app, register):
    routing = app.ui5.get("routing", {})
    routes = {r["name"]: r.get("target") for r in routing.get("routes", [])}
    bad = [f"route {r}: target {t} does not exist" for r, t in routes.items()
           if t not in app.targets]
    for key, t in app.targets.items():
        for entity, nav in app.settings(t).get("navigation", {}).items():
            route = nav.get("detail", {}).get("route")
            if route not in routes:
                bad.append(f"{key}: navigation {entity} names route {route}, which does not exist")
    bad += [f"target {k}: no route reaches it" for k in app.targets if k not in routes.values()]
    return bad


def check_load(app, register):
    if not INITIAL_LOAD:
        return None
    return [f"{k}: initialLoad is not {INITIAL_LOAD}" for k, t in app.list_reports().items()
            if app.settings(t).get("initialLoad") != INITIAL_LOAD]


def check_ids(app, register):
    bad = []
    app_id = app.manifest.get("sap.app", {}).get("id", "")
    comp = (app.folder / "Component.js").read_text() if (app.folder / "Component.js").exists() else ""
    if f'"{app_id}.Component"' not in comp:
        bad.append(f"Component.js does not extend {app_id}.Component")
    bundle = app.ui5.get("models", {}).get("i18n", {}).get("settings", {}).get("bundleName", "")
    if bundle != f"{app_id}.i18n.i18n":
        bad.append(f"i18n bundleName {bundle} is not {app_id}.i18n.i18n")
    index = app.folder / "index.html"
    if index.exists() and f'"{app_id}"' not in index.read_text():
        bad.append(f"index.html does not name {app_id}")
    if len(app.name) > BSP_NAME_MAX:
        bad.append(f"BSP name {app.name.upper()} is longer than {BSP_NAME_MAX} characters")
    if register is not None and f"`{app.name.upper()}`" not in register:
        bad.append(f"BSP application {app.name.upper()} is not in the object register")
    v = app.ui5.get("dependencies", {}).get("minUI5Version", "0.0")
    if SYSTEM_UI5 and tuple(int(x) for x in v.split(".")[:2]) > SYSTEM_UI5:
        bad.append(f"minUI5Version {v} is above the system's {'.'.join(map(str, SYSTEM_UI5))}")
    return bad


CHECKS = [
    ("service", "data source is a registered V4 binding", check_service),
    ("entities", "entity sets and associations resolve", check_entities),
    ("views", "view annotation paths are annotated", check_views),
    ("tables", "configured tables exist and are grid tables", check_tables),
    ("routing", "navigation, routes and targets resolve", check_routing),
    ("load", "list reports start without loading", check_load),
    ("ids", "app id, names and UI5 version agree", check_ids),
]


def _register():
    """The register's text, or None when the project keeps none."""
    f = path("register.file")
    return f.read_text() if f and f.is_file() else None


def _per_app(fn):
    """One check across every app: findings prefixed with the app, or Skip."""
    def run_it():
        register, found = _register(), apps()
        bad = []
        for name, folder in found.items():
            res = fn(App(name, folder), register)
            if res is None:
                return needs("[app] initial_load")
            bad += [Finding(f"{name}: {b}", f"{name}: {b}") for b in res]
        return bad, [f"{len(found)} app(s)"]
    return run_it


if __name__ == "__main__":
    empty = not apps()
    exit_with(run(SCRIPT, [(k, d, _per_app(fn)) for k, d, fn in CHECKS], suppressed,
                  empty=empty, empty_why="no app under the UI root"))
