#!/usr/bin/env python3
"""The runner every script shares, and check_all.py over all of them."""

import unittest

from _project import CLASS, IFACE, project


class Runner(unittest.TestCase):

    def test_stale_suppression_is_a_finding(self):
        p = project({"src/zif_a.intf.abap": IFACE},
                    '[suppress.standing.orphans]\n"zif_a.gone" = "was called once"\n')
        _, out = p.run("check_standing.py")
        p.close()
        self.assertIn("orphans: `zif_a.gone` excused nothing", out)

    def test_suppression_for_a_check_that_does_not_exist(self):
        p = project({"src/zif_a.intf.abap": IFACE},
                    '[suppress.standing.orphanz]\n"x" = "typo"\n')
        _, out = p.run("check_standing.py")
        p.close()
        self.assertIn("orphanz: no such check in standing", out)

    def test_unknown_check_name_is_an_error(self):
        p = project({"src/zif_a.intf.abap": IFACE})
        rc, out = p.run("check_standing.py", "grpah")
        p.close()
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown check(s) grpah", out)

    def test_empty_corpus_is_not_ok(self):
        p = project({})
        rc, out = p.run("check_standing.py", "orphans")
        p.close()
        self.assertIn("--   orphans", out)
        self.assertNotIn("ok   orphans", out)
        self.assertEqual(rc, 0)

    def test_convention_turned_off(self):
        p = project({"src/zcl_a.clas.abap": CLASS, "src/zif_a.intf.abap": IFACE},
                    '[checks]\noff = ["standing.loops"]\n')
        _, out = p.run("check_standing.py", "loops")
        p.close()
        self.assertIn("--   loops", out)
        self.assertIn("turned off", out)

    def test_no_config_at_all(self):
        p = project({"src/zif_a.intf.abap": IFACE})
        (p.root / "abapcheck.toml").unlink()
        rc, out = p.run("check_standing.py", "orphans", "--project", str(p.root))
        p.close()
        self.assertIn("no abapcheck.toml", out)
        self.assertIn("✗ zif_a.unused", out)


class Listing(unittest.TestCase):

    def test_list_names_every_check_and_marks_the_ones_turned_off(self):
        p = project({}, '[checks]\noff = ["loops"]\n')
        rc, out = p.run("check_standing.py", "--list")
        p.close()
        self.assertEqual(rc, 0)
        self.assertIn("  undrafted    objects named but not on disk\n", out)
        self.assertIn("  loops        LOOP AT ... ASSIGNING, not INTO (off)\n", out)
        self.assertNotIn("finding(s)", out)


class CheckAll(unittest.TestCase):

    CONFIG = '''
        [[ddic.domain]]
        name = "ZA_STATE"
        type = "CHAR"
        length = 1
        text = "State"
        values = [["O", "Open"]]

        [[ddic.element]]
        name = "ZA_STATE"
        domain = "ZA_STATE"
        short = "State"
        medium = "State"
        long = "State"

        [[ddic.table]]
        name = "ZA_T"
        delivery = "C"
        text = "Settings"
        fields = [["MANDT", "MANDT", true], ["STATE", "ZA_STATE", true]]

        [[ddic.lock]]
        name = "EZA_T"
        table = "ZA_T"
        mode = "E"
        args = ["MANDT", "STATE"]

        [meta]
        package = "Demo"
        [meta.classes]
        zcl_a = "Reader"
        [meta.interfaces]
        zif_a = "Promise"
        [meta.programs]
        za_r = "Report"
        '''

    def test_exit_code_is_the_number_of_scripts_that_failed(self):
        p = project({
            "src/zif_a.intf.abap": "INTERFACE zif_a PUBLIC.\nENDINTERFACE.\n",
            "src/za_r.prog.abap": "REPORT za_r.\n",
            "src/zcl_a.clas.abap": """
                CLASS zcl_a DEFINITION PUBLIC.
                ENDCLASS.
                CLASS zcl_a IMPLEMENTATION.
                  METHOD m.
                    SELECT state FROM za_t INTO TABLE @DATA(lt) WHERE state = @lv.
                  ENDMETHOD.
                ENDCLASS.
                """}, self.CONFIG)
        for gen in ("make_ddic.py", "make_meta.py"):
            rc, out = p.run(gen)
            self.assertEqual(rc, 0, out)
        for name in ("za_state.doma.xml", "eza_t.enqu.xml", "zif_a.intf.xml", "za_r.prog.xml"):
            self.assertTrue((p.root / "src" / name).is_file(), name)

        rc, out = p.run("check_all.py", "--with", "stubs")
        self.assertIn("━━ 13 of 13 passed", out)
        self.assertEqual(rc, 0, out)

        (p.root / "src/zcl_b.clas.abap").write_text(
            "CLASS zcl_b IMPLEMENTATION.\n  METHOD m.\n    IF is_x( ).\n    ENDIF.\n"
            "    LOOP AT lt INTO DATA(ls).\n    ENDLOOP.\n  ENDMETHOD.\nENDCLASS.\n")
        lock = p.root / "src/eza_t.enqu.xml"
        lock.write_text(lock.read_text().replace("<ENQMODE>E</ENQMODE>", "<ENQMODE>X</ENQMODE>"))
        rc, out = p.run("check_all.py")
        p.close()
        self.assertIn("failed: check_standing.py", out)
        self.assertIn("check_bare_bool.py (1)", out)
        self.assertIn("make_ddic.py (1)", out)
        self.assertIn("make_meta.py (1)", out)      # zcl_b has no description
        self.assertEqual(rc, 4, out)

    def test_malformed_xml_names_the_file(self):
        p = project({}, self.CONFIG)
        p.run("make_ddic.py")
        (p.root / "src/za_t.tabl.xml").write_text("<a></a>junk")
        rc, out = p.run("check_standing.py", "ddic")
        p.close()
        self.assertEqual(rc, 1)
        self.assertIn("za_t.tabl.xml: not well-formed XML", out)
        self.assertNotIn("Traceback", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
