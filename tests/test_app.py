#!/usr/bin/env python3
"""check_app.py: Fiori elements apps against their service."""

import unittest

from _project import crosses, fixture, project


class App(unittest.TestCase):

    def test_routing(self):
        manifest = """
            {"sap.app": {"id": "z.app", "dataSources": {"mainService": {
                "uri": "/sap/opu/odata4/sap/zsb_x/srvd/sap/zsd_x/0001/",
                "settings": {"odataVersion": "4.0"}}}},
             "sap.ui5": {"routing": {"routes": [{"name": "main", "target": "nowhere"}],
                                     "targets": {"List": {"name": "sap.fe.templates.ListReport",
                                       "options": {"settings": {"contextPath": "/X"}}}}}}}
            """
        p = project({"src/zsd_x.srvd.srvdsrv": "define service ZSD_X { expose ZC_X as X; }",
                     "ui/zapp/manifest.json": manifest})
        _, out = p.run("check_app.py", "routing", "load")
        p.close()
        self.assertIn("route main: target nowhere does not exist", out)
        self.assertIn("target List: no route reaches it", out)
        self.assertIn("--   load", out)

    def test_every_check(self):
        """`zgood` passes all seven checks; `zbad_too_long_name` and `zraw`
        fail each of them."""
        p = fixture("app")
        _, out = p.run("check_app.py")
        p.close()
        bad = "zbad_too_long_name"
        self.assertEqual(crosses(out), [
            f"{bad}: binding ZSB_Y is not in the object register",
            f"{bad}: mainService is not odataVersion 4.0",
            "zraw: /sap/opu/odata/sap/ZX_SRV/: not an OData V4 service-binding URL",
            f"{bad}: List: /Nowhere: entity set Nowhere is not exposed by zsd_x",
            f"{bad}: List/t1: ZC_ROOT has no @UI.selectionVariant qualifier 'Closed'",
            f"{bad}: List: @com.sap.vocabularies.UI.v1.LineItem is ResponsiveTable, not GridTable",
            f"{bad}: List: /Root/_Missing: ZC_ROOT defines no association _Missing",
            f"{bad}: List: controlConfiguration key bogus not understood",
            f"{bad}: List: navigation Root names route nope, which does not exist",
            f"{bad}: List: initialLoad is not Disabled",
            f"{bad}: Component.js does not extend zbad.Component",
            f"{bad}: i18n bundleName wrong.bundle is not zbad.i18n.i18n",
            f"{bad}: index.html does not name zbad",
            f"{bad}: BSP name ZBAD_TOO_LONG_NAME is longer than 15 characters",
            f"{bad}: BSP application ZBAD_TOO_LONG_NAME is not in the object register",
            f"{bad}: minUI5Version 1.130.0 is above the system's 1.120",
            "zraw: Component.js does not extend zraw.Component",
            "zraw: i18n bundleName  is not zraw.i18n.i18n",
            "zraw: BSP application ZRAW is not in the object register",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=1)
