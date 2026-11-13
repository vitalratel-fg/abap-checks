#!/usr/bin/env python3
"""check_design.py: the package's agreements about tables and reports."""

import unittest

from _project import crosses, project


class Design(unittest.TestCase):

    def test_owners_and_eventblocks(self):
        cfg = '''
            [[ddic.element]]
            name = "ZX_ID"
            type = ["CHAR", 10]
            short = "Id"
            medium = "Id"
            long = "Identifier"

            [[ddic.table]]
            name = "ZT_X"
            delivery = "A"
            text = "X"
            fields = [["MANDT", "MANDT", true], ["ID", "ZX_ID", true]]
            '''
        p = project({
            "src/zcl_one.clas.abap": "CLASS zcl_one DEFINITION PUBLIC.\nENDCLASS.\nCLASS zcl_one IMPLEMENTATION.\n"
                                     "  METHOD m.\n    SELECT id FROM zt_x INTO TABLE @DATA(lt).\n  ENDMETHOD.\nENDCLASS.\n",
            "src/zcl_two.clas.abap": "CLASS zcl_two DEFINITION PUBLIC.\nENDCLASS.\nCLASS zcl_two IMPLEMENTATION.\n"
                                     "  METHOD m.\n    INSERT zt_x FROM @ls.\n  ENDMETHOD.\nENDCLASS.\n",
            "src/zr_x.prog.abap": "REPORT zr_x.\nSTART-OF-SELECTION.\n  IF 1 = 1.\n  ENDIF.\n"}, cfg)
        rc, out = p.run("make_ddic.py")
        self.assertEqual(rc, 0, out)
        _, out = p.run("check_design.py")
        p.close()
        self.assertIn("zt_x is written or read by zcl_one, zcl_two", out)
        self.assertIn("zr_x:3 IF inside START-OF-SELECTION", out)
        self.assertIn("--   register", out)


class EventBlocks(unittest.TestCase):

    def test_logic_inside_an_event_block_and_nowhere_else(self):
        """Declarations, constructions and calls are what an event block holds;
        a SELECT is logic like any other; a CLASS or FORM ends the block."""
        p = project({"src/zr_e.prog.abap": """
            REPORT zr_e.
            PARAMETERS p_x TYPE i.
            INITIALIZATION.
              DATA(lo_app) = NEW lcl_app( ).
            AT SELECTION-SCREEN ON p_x.
              IF p_x < 0.
                MESSAGE e001(zx).
              ENDIF.
            START-OF-SELECTION.
              lo_app->run( ).
              SELECT * FROM zt INTO TABLE @DATA(lt).
              LOOP AT lt ASSIGNING FIELD-SYMBOL(<l>).
              ENDLOOP.
            CLASS lcl_app DEFINITION.
              PUBLIC SECTION.
                METHODS run.
            ENDCLASS.
            CLASS lcl_app IMPLEMENTATION.
              METHOD run.
                IF 1 = 1.
                ENDIF.
              ENDMETHOD.
            ENDCLASS.
            END-OF-SELECTION.
              TRY.
                  lo_app->run( ).
                CATCH cx_root.
              ENDTRY.
            FORM legacy.
              DO 3 TIMES.
              ENDDO.
            ENDFORM.
            """}, "[suppress.design.eventblocks]\n'zr_e:AT SELECTION-SCREEN ON p_x' = \"validation\"\n")
        _, out = p.run("check_design.py", "eventblocks")
        p.close()
        self.assertEqual(crosses(out), [
            "zr_e:11 SELECT inside START-OF-SELECTION - an event block declares, constructs and calls",
            "zr_e:12 LOOP inside START-OF-SELECTION - an event block declares, constructs and calls",
            "zr_e:25 TRY inside END-OF-SELECTION - an event block declares, constructs and calls",
        ])
        self.assertIn("suppressed: zr_e:AT SELECTION-SCREEN ON p_x - validation", out)


class DesignData(unittest.TestCase):

    def test_columns_and_values(self):
        """A column counts as read by a WHERE, a join alias, or a fetch whose
        `-column` the source uses -- never by the value going into the
        table's own write; a C table need not be written. A value counts as
        assigned in a VALUE or a SET, not in a WHERE or an IF."""
        cfg = '''
            [[ddic.domain]]
            name = "ZX_STATE"
            type = "CHAR"
            length = 1
            text = "State"
            values = [["O", "Open"], ["D", "Done"], ["C", "Cancelled"], ["X", "Unnamed"], ["W", "Waiting"]]

            [[ddic.element]]
            name = "ZX_STATE"
            domain = "ZX_STATE"
            short = "State"
            medium = "State"
            long = "State"

            [[ddic.element]]
            name = "ZX_ID"
            type = ["CHAR", 10]
            short = "Id"
            medium = "Id"
            long = "Identifier"

            [[ddic.table]]
            name = "ZT_DOC"
            delivery = "A"
            text = "Docs"
            fields = [["MANDT", "MANDT", true], ["ID", "ZX_ID", true], ["STATE", "ZX_STATE", false],
                      ["NOTE", "ZX_ID", false], ["SPARE", "ZX_ID", false], ["DONE_BY", "ZX_ID", false]]

            [[ddic.table]]
            name = "ZT_CUST"
            delivery = "C"
            text = "Custom"
            fields = [["MANDT", "MANDT", true], ["KEYF", "ZX_ID", true], ["VAL", "ZX_ID", false]]

            [[ddic.table]]
            name = "ZT_LOG"
            delivery = "A"
            text = "Log"
            fields = [["MANDT", "MANDT", true], ["LID", "ZX_ID", true], ["MSG", "ZX_ID", false]]

            [[ddic.table]]
            name = "ZT_JOIN"
            delivery = "A"
            text = "Joined"
            fields = [["MANDT", "MANDT", true], ["JID", "ZX_ID", true], ["WERKS", "ZX_ID", false],
                      ["UNUSED", "ZX_ID", false]]
            '''
        p = project({"src/zcl_doc.clas.abap": """
            CLASS zcl_doc DEFINITION PUBLIC.
              PUBLIC SECTION.
                CONSTANTS:
                  BEGIN OF gc_state,
                    open      TYPE zx_state VALUE 'O',
                    done      TYPE zx_state VALUE 'D',
                    cancelled TYPE zx_state VALUE 'C',
                    waiting   TYPE zx_state VALUE 'W',
                  END OF gc_state.
            ENDCLASS.

            CLASS zcl_doc IMPLEMENTATION.
              METHOD write.
                INSERT zt_doc FROM @( VALUE #( id = lv_id state = gc_state-open note = ls_in-spare ) ).
                UPDATE zt_doc SET state = @gc_state-done, done_by = @sy-uname WHERE id = @lv_id.
                INSERT zt_log FROM @ls_log.
              ENDMETHOD.
              METHOD read.
                SELECT id, note FROM zt_doc WHERE state <> @gc_state-cancelled INTO TABLE @DATA(lt_doc).
                LOOP AT lt_doc ASSIGNING FIELD-SYMBOL(<ls>).
                  lv = <ls>-note.
                ENDLOOP.
                IF ls-state = gc_state-waiting.
                ENDIF.
                SELECT d~id FROM zt_doc AS d INNER JOIN zt_join AS j ON j~jid = d~id WHERE j~werks = @lv INTO TABLE @DATA(lt_j).
                SELECT * FROM zt_cust INTO TABLE @DATA(lt_c).
              ENDMETHOD.
            ENDCLASS.
            """}, cfg)
        rc, out = p.run("make_ddic.py")
        self.assertEqual(rc, 0, out)
        _, out = p.run("check_design.py", "columns", "values")
        p.close()
        self.assertEqual(crosses(out), [
            "zt_cust.keyf: nothing reads it",
            "zt_cust.val: nothing reads it",
            "zt_doc.spare: nothing reads it",
            "zt_doc.spare: nothing writes it",
            "zt_doc.done_by: nothing reads it",
            "zt_join.jid: nothing writes it",
            "zt_join.werks: nothing writes it",
            "zt_join.unused: nothing reads it",
            "zt_join.unused: nothing writes it",
            "zt_log: no statement reads the table",
            "gc_state: zt_doc can hold C, and nothing assigns it - it is only compared against",
            "gc_state: zt_doc can hold X, and no member of the group carries it",
            "gc_state: zt_doc can hold W, and nothing assigns it - it is only compared against",
        ])


class Register(unittest.TestCase):

    def test_lists_not_counts(self):
        """Objects on disk (a subpackage's folder among them, a README not)
        must be in the register; a subset document's names must reach it; a
        planned name is a note, and an ignored one not even that."""
        cfg = """
            [package]
            devc = "z_demo"
            own = 'z\\w+'

            [register]
            file = "docs/naming.md"
            names = '`((?:z|ez)\\w+)`'
            planned_ignore = '^ez'

            [[register.subset]]
            label = "Tables"
            file = "docs/architecture.md"
            section = '^## 2\\. Tables\\n'
            names = '^\\| `(ZT_\\w+)`'

            [[register.subset]]
            file = "docs/missing.md"
            section = '^## Nope\\n'
            names = '`(Z\\w+)`'
            """
        devc = ('<?xml version="1.0"?><asx:abap xmlns:asx="http://www.sap.com/abapxml">'
                "<asx:values><DEVC><CTEXT>Demo</CTEXT></DEVC></asx:values></asx:abap>")
        p = project({
            "docs/naming.md": "# Names\n\n| `Z_DEMO` | package |\n| `ZCL_A` | class |\n"
                              "| `ZT_DOC` | table |\n| `ZCL_LATER` | planned |\n| `EZ_LOCK` | lock |\n",
            "docs/architecture.md": "# Architecture\n\n## 1. Classes\n| `ZT_NOT_A_TABLE_SECTION` | x |\n\n"
                                    "## 2. Tables\n| `ZT_DOC` | docs |\n| `ZT_NEW` | not registered |\n\n"
                                    "## 3. Later\n",
            "src/package.devc.xml": devc,
            "src/sub/package.devc.xml": devc,
            "src/zcl_a.clas.abap": "CLASS zcl_a DEFINITION PUBLIC.\nENDCLASS.\n",
            "src/sub/zcl_stray.clas.abap": "CLASS zcl_stray DEFINITION PUBLIC.\nENDCLASS.\n",
            "src/zt_doc.tabl.xml": "<x/>",
            "src/README.md": "notes",
        }, cfg)
        rc, out = p.run("check_design.py", "register")
        p.close()
        self.assertEqual(crosses(out), [
            "on disk, not in the object register: z_demo_sub",
            "on disk, not in the object register: zcl_stray",
            "Tables names zt_new, the object register does not",
            "missing.md: section /^## Nope\\n/ not found in docs/missing.md",
        ])
        self.assertIn("5 object(s) on disk, 5 in the register", out)
        self.assertIn("Tables: 2 name(s), 1 built", out)
        self.assertIn("1 named but not built yet: ZCL_LATER", out)
        self.assertEqual(rc, 4)


if __name__ == "__main__":
    unittest.main(verbosity=1)
