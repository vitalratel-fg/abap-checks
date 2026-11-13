#!/usr/bin/env python3
"""check_stubs.py: the report of empty and blocked methods."""

import unittest

from _project import project


class Stubs(unittest.TestCase):

    FILES = {
        "src/zif_s.intf.abap": """
            INTERFACE zif_s PUBLIC.
              "! Waits for OPEN-10: which ledger.
              METHODS ledger.
              "! TODO: decide the rounding.
              METHODS rounding.
              "! Plain, nothing open.
              METHODS plain.
            ENDINTERFACE.
            """,
        "src/zcl_s.clas.abap": """
            CLASS zcl_s DEFINITION PUBLIC.
              PUBLIC SECTION.
                "! Blocked on OPEN-2: the tax rule.
                METHODS taxed.
                METHODS surcharge RETURNING VALUE(rv_amount) TYPE p.
            ENDCLASS.

            CLASS zcl_s IMPLEMENTATION.
              METHOD empty_one.
              ENDMETHOD.
              METHOD prose_only.
                " Read the table, then group the rows by plant before summing.
              ENDMETHOD.
              METHOD taxed.
                lv_x = 1.
              ENDMETHOD.
              METHOD waiting.
                " BLOCKED until OPEN-3 says which plant.
              ENDMETHOD.
              METHOD surcharge.
                IF lv_flag = abap_false.
                  RETURN.
                ENDIF.
                " Look up the surcharge and return it, someday.
              ENDMETHOD.
              METHOD branches.
                CASE lv_kind.
                  WHEN 'A'.
                    lv_y = 1.
                  WHEN 'B'.
                    " Handle kind B the same way as kind A, but scaled.
                  WHEN 'C'.
                  WHEN 'D'.
                    lv_y = 2.
                ENDCASE.
              ENDMETHOD.
              METHOD answered.
                " OPEN-8 answered: the rule stands.
                lv_z = 3.
              ENDMETHOD.
              METHOD hook.
                " INTENTIONALLY EMPTY: subclasses override it.
              ENDMETHOD.
              METHOD file_io.
                OPEN DATASET lv_file FOR INPUT IN TEXT MODE ENCODING DEFAULT.
              ENDMETHOD.
              METHOD written.
                lv_w = 4.
              ENDMETHOD.
            ENDCLASS.

            * The reversal posting is not written out here yet.
            * It is BLOCKED until finance confirms the account,
            * recorded as OPEN-11a in the register, and it needs
            * a method of its own once that is decided.""",
    }
    CONFIG = "[stubs]\nblockers = '\\bOPEN-(\\d+(?:[a-z]\\b)?)'\n"

    def test_empty_and_blocked_are_kept_apart(self):
        """A guard clause before prose, or an arm of comments, is still empty;
        an answered citation, an intentional hook, OPEN DATASET and a `WHEN`
        that falls through are not reported. A note at the foot of a file,
        outside every method, is."""
        p = project(self.FILES, self.CONFIG)
        rc, out = p.run("check_stubs.py")
        p.close()
        rows = [l.split() for l in out.splitlines() if l[:2] in ("E-", "-B", "EB")]
        self.assertEqual([(r[0], r[1], r[2], r[3:]) for r in rows], [
            ("EB", "zcl_s.clas.abap", "(no", ["method)", "OPEN-11A"]),
            ("E-", "zcl_s.clas.abap", "BRANCHES", []),
            ("E-", "zcl_s.clas.abap", "EMPTY_ONE", []),
            ("E-", "zcl_s.clas.abap", "PROSE_ONLY", []),
            ("E-", "zcl_s.clas.abap", "SURCHARGE", []),
            ("-B", "zcl_s.clas.abap", "TAXED", ["OPEN-2"]),
            ("EB", "zcl_s.clas.abap", "WAITING", ["OPEN-3"]),
            ("-B", "zif_s.intf.abap", "LEDGER", ["OPEN-10"]),
            ("-B", "zif_s.intf.abap", "ROUNDING", []),
        ])
        self.assertIn("9 methods: 6 empty, 5 blocked, 2 both", out)
        self.assertEqual(rc, 9)

    def test_markdown_groups_by_open_point_in_natural_order(self):
        p = project(self.FILES, self.CONFIG)
        _, out = p.run("check_stubs.py", "--md")
        p.close()
        self.assertEqual([l for l in out.splitlines() if l.startswith("###")],
                         ["### OPEN-2", "### OPEN-3", "### OPEN-10", "### OPEN-11A"])
        self.assertIn("- `WAITING` — zcl_s.clas.abap", out)


if __name__ == "__main__":
    unittest.main(verbosity=1)
