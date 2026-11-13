#!/usr/bin/env python3
"""make_ddic.py and make_meta.py: generation, drift, validation."""

import unittest

from _project import FIXTURES, fixture, project


class Generators(unittest.TestCase):

    def test_write_check_and_validate(self):
        cfg = '''
            [[ddic.table]]
            name = "ZT_LONGER_THAN_16"
            delivery = "A"
            text = "Too long"
            fields = [["MANDT", "MANDT", true], ["X", "ZNOWHERE", false]]
            '''
        p = project({}, cfg)
        rc, out = p.run("make_ddic.py")
        self.assertNotEqual(rc, 0)
        self.assertIn("DDIC table limit is 16", out)
        self.assertIn("ZNOWHERE is neither defined here", out)
        p.close()

        cfg = '''
            [meta]
            package = "Demo"
            [meta.classes]
            zcl_g = "Generated"
            '''
        p = project({"src/zcl_g.clas.abap": "CLASS zcl_g DEFINITION PUBLIC.\nENDCLASS.\n",
                     "src/zcl_h.clas.abap": "CLASS zcl_h DEFINITION PUBLIC.\nENDCLASS.\n"}, cfg)
        rc, out = p.run("make_meta.py")
        self.assertIn("zcl_h.clas.abap: no description", out)
        (p.root / "src/zcl_h.clas.abap").unlink()
        rc, out = p.run("make_meta.py")
        self.assertEqual(rc, 0, out)
        rc, out = p.run("make_meta.py", "--check")
        self.assertIn("0 drifted", out)
        (p.root / "src/zcl_g.clas.xml").write_text("changed")
        rc, out = p.run("make_meta.py", "--check")
        p.close()
        self.assertIn("zcl_g.clas.xml differs", out)
        self.assertEqual(rc, 1)


class DdicGeneration(unittest.TestCase):

    def test_xml_is_what_abapgit_serialises(self):
        """Elements, a table with currency references and indexes: the files
        written are tests/fixtures/ddic_generate/expected, byte for byte."""
        p = fixture("ddic_generate")
        rc, out = p.run("make_ddic.py")
        self.assertEqual(rc, 0, out)
        expected = FIXTURES / "ddic_generate" / "expected"
        for want in sorted(expected.iterdir()):
            self.assertEqual((p.root / "src" / want.name).read_text(), want.read_text(), want.name)
        p.close()


class DdicValidation(unittest.TestCase):

    def test_every_definition_error_and_no_crash(self):
        """An element on an undefined domain is reported, and a field typed by
        it does not crash the validator that reports it."""
        p = fixture("ddic_validate")
        rc, out = p.run("make_ddic.py", "--check")
        p.close()
        t = "ZV_T_NAME_TOO_LONG"
        self.assertEqual([l.strip()[2:] for l in out.splitlines() if l.strip().startswith("✗")], [
            "ZV_STD_DOMAIN: domain WAERS is not defined here -- a standard domain makes the "
            "element unresolvable offline; use a predefined type instead",
            "ZV_AN_ELEMENT_NAME_LONGER_THAN_30: 33 characters, limit is 30",
            f"{t}: 18 characters, DDIC table limit is 16",
            f"{t}: delivery class X has no data class in DATA_CLASS",
            f"{t}-AMT: CURR without a reference field",
            f"{t}-AMT2: reference STATE is not a CUKY field",
            f"{t}-ODD: ZV_NOWHERE is neither defined here nor a standard element with a type in "
            "[ddic.standard], so the field cannot be parsed without the SAP system",
            f"{t}~Z1: an index name is exactly 3 characters",
            f"{t}~Z02: no field MISSING",
            "EZV_GONE: primary table ZV_T_GONE is not defined here",
            "EZV_OK: ZV_T_OK has no field NOPE",
        ])
        self.assertEqual(rc, 11)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
