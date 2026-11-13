#!/usr/bin/env python3
"""The per-file checks: keyed rows, bare booleans, clobbered writes, model writers."""

import unittest

from _project import SuppressionAsserts, crosses, project


class PerFile(unittest.TestCase):

    def test_bare_bool(self):
        p = project({"src/zcl_b.clas.abap": """
            CLASS zcl_b IMPLEMENTATION.
              METHOD m.
                IF is_ready( iv_x = 1 ).
                ENDIF.
                IF is_ready( iv_x = 1 ) = abap_true.
                ENDIF.
                IF line_exists( lt[ 1 ] ).
                ENDIF.
              ENDMETHOD.
            ENDCLASS.
            """})
        _, out = p.run("check_bare_bool.py")
        p.close()
        self.assertIn("zcl_b.clas.abap:3", out)
        self.assertEqual(out.count("✗"), 1, out)

    def test_clobbered(self):
        p = project({"src/zcl_c.clas.abap": """
            CLASS zcl_c IMPLEMENTATION.
              METHOD m.
                rs_item-reason = iv_reason.
                rs_item = _mo_engine->read( ).
              ENDMETHOD.
              METHOD ok.
                rs_item = _mo_engine->read( ).
                rs_item-reason = iv_reason.
              ENDMETHOD.
            ENDCLASS.
            """})
        _, out = p.run("check_clobbered_writes.py")
        p.close()
        self.assertIn("rs_item-reason written at line 3", out)
        self.assertEqual(out.count("✗"), 1, out)

    def test_clobbered_across_blocks(self):
        """A write and a wholesale assignment at one level clash; a write in an
        arm or a closed block is one alternative, not a clash."""
        p = project({"src/zcl_c.clas.abap": """
            CLASS zcl_c IMPLEMENTATION.
              METHOD arms.
                IF lv_a = 1.
                  rs_x-a = 1.
                ELSE.
                  rs_x = get( ).
                ENDIF.
              ENDMETHOD.
              METHOD closed.
                IF lv_a = 1.
                  rs_x-a = 1.
                ENDIF.
                rs_x = get( ).
              ENDMETHOD.
              METHOD same_level.
                LOOP AT lt ASSIGNING FIELD-SYMBOL(<l>).
                  rs_x-b = <l>.
                  rs_x-c-d = 2.
                  rs_x = get( ).
                ENDLOOP.
              ENDMETHOD.
              METHOD outer.
                rs_x-e = 1.
                TRY.
                    rs_x = get( ).
                  CATCH cx_root.
                ENDTRY.
              ENDMETHOD.
            ENDCLASS.
            """})
        _, out = p.run("check_clobbered_writes.py")
        p.close()
        self.assertEqual([f.split("  ", 1)[1] for f in crosses(out)], [
            "same_level: rs_x-b written at line 17, then rs_x assigned wholesale",
            "same_level: rs_x-c-d written at line 18, then rs_x assigned wholesale",
            "outer: rs_x-e written at line 23, then rs_x assigned wholesale",
        ])

    def test_sorted_rows(self):
        p = project({"src/zcl_s.clas.abap": """
            CLASS zcl_s IMPLEMENTATION.
              METHOD m.
                TYPES mty_rows TYPE SORTED TABLE OF mty_row WITH UNIQUE KEY id.
                DATA lt_rows TYPE mty_rows.
                LOOP AT lt_rows ASSIGNING FIELD-SYMBOL(<ls_row>).
                  <ls_row>-id = 1.
                  <ls_row>-text = 'fine'.
                ENDLOOP.
              ENDMETHOD.
            ENDCLASS.
            """})
        _, out = p.run("check_sorted_rows.py")
        p.close()
        self.assertIn("KEY", out)
        self.assertIn("<ls_row>-id", out)
        self.assertNotIn("<ls_row>-text", out)


class SortedRows(unittest.TestCase):

    def test_every_rule_and_what_is_not_a_finding(self):
        """Each rule of the header fires once per form, and nothing it lists
        as legal does: EXPORTING a row (18), a non-key component (19, 30),
        INSERT ... INTO TABLE (48), MODIFY TABLE ... FROM (49)."""
        p = project({"src/zcl_s.clas.abap": """
            CLASS zcl_s DEFINITION PUBLIC.
              PUBLIC SECTION.
                TYPES mty_rows TYPE SORTED TABLE OF mty_row WITH UNIQUE KEY id.
                TYPES mty_alias TYPE mty_rows.
                TYPES mty_all TYPE HASHED TABLE OF mty_row WITH UNIQUE DEFAULT KEY.
                DATA mt_attr TYPE mty_rows.
                METHODS take CHANGING ct_rows TYPE mty_alias.
                METHODS give RETURNING VALUE(rt_rows) TYPE mty_rows.
                METHODS fill CHANGING cs_row TYPE mty_row.
                METHODS show IMPORTING is_row TYPE mty_row.
            ENDCLASS.

            CLASS zcl_s IMPLEMENTATION.
              METHOD bind.
                DATA lt_rows TYPE mty_rows.
                LOOP AT lt_rows ASSIGNING FIELD-SYMBOL(<ls_row>).
                  fill( CHANGING cs_row = <ls_row> ).
                  show( EXPORTING is_row = <ls_row> ).
                  <ls_row>-text = 'fine'.
                ENDLOOP.
              ENDMETHOD.
              METHOD row.
                LOOP AT mt_attr ASSIGNING FIELD-SYMBOL(<ls_a>).
                  <ls_a> = VALUE #( ).
                  CLEAR <ls_a>.
                  MOVE-CORRESPONDING ls_other TO <ls_a>.
                ENDLOOP.
                mt_attr[ id = 1 ] = ls_other.
                mt_attr[ id = 1 ]-id = 2.
                mt_attr[ id = 1 ]-text = 'fine'.
              ENDMETHOD.
              METHOD key.
                DATA lt_all TYPE mty_all.
                READ TABLE lt_all REFERENCE INTO DATA(lr_row) INDEX 1.
                lr_row->text = 'x'.
                lr_row->* = ls_other.
                ASSIGN lt_all[ 1 ] TO FIELD-SYMBOL(<ls_k>).
                SELECT SINGLE id FROM zt INTO <ls_k>-id.
              ENDMETHOD.
              METHOD take.
                LOOP AT ct_rows ASSIGNING FIELD-SYMBOL(<ls_c>).
                  CLEAR <ls_c>-id.
                ENDLOOP.
                APPEND ls_other TO ct_rows.
                SORT ct_rows BY text.
                INSERT ls_other INTO ct_rows INDEX 1.
                MODIFY ct_rows FROM ls_other INDEX 1.
                INSERT ls_other INTO TABLE ct_rows.
                MODIFY TABLE ct_rows FROM ls_other.
              ENDMETHOD.
              METHOD returned.
                DATA(lt_got) = give( ).
                LOOP AT lt_got ASSIGNING FIELD-SYMBOL(<ls_g>).
                  <ls_g>-id = 3.
                ENDLOOP.
              ENDMETHOD.
              METHOD final.
                FINAL(lt_fin) = VALUE string_table( ).
                LOOP AT lt_fin ASSIGNING FIELD-SYMBOL(<ls_f>).
                  <ls_f> = 'x'.
                ENDLOOP.
                APPEND 'y' TO lt_fin.
                lt_fin = VALUE #( ).
              ENDMETHOD.
            ENDCLASS.
            """})
        rc, out = p.run("check_sorted_rows.py")
        p.close()
        found = [" ".join(f.split("|")[0].split()) for f in crosses(out)]
        self.assertEqual(found, [
            "zcl_s.clas.abap:17 BIND <ls_row> (row of lt_rows) bound whole to CHANGING",
            "zcl_s.clas.abap:24 ROW <ls_a> (row of mt_attr) assigned",
            "zcl_s.clas.abap:25 ROW <ls_a> (row of mt_attr) cleared",
            "zcl_s.clas.abap:26 ROW <ls_a> (row of mt_attr) MOVE-CORRESPONDING target",
            "zcl_s.clas.abap:28 ROW mt_attr[ ... ] assigned whole",
            "zcl_s.clas.abap:29 KEY mt_attr[ ... ] key written",
            "zcl_s.clas.abap:35 KEY lr_row->text (row of lt_all) assigned",
            "zcl_s.clas.abap:36 ROW lr_row (row of lt_all) assigned",
            "zcl_s.clas.abap:38 KEY <ls_k>-id (row of lt_all) INTO target",
            "zcl_s.clas.abap:42 KEY <ls_c>-id (row of ct_rows) cleared",
            "zcl_s.clas.abap:44 TABLE ct_rows is keyed",
            "zcl_s.clas.abap:45 TABLE ct_rows is keyed",
            "zcl_s.clas.abap:46 TABLE ct_rows is keyed",
            "zcl_s.clas.abap:47 TABLE ct_rows is keyed",
            "zcl_s.clas.abap:54 KEY <ls_g>-id (row of lt_got) assigned",
            "zcl_s.clas.abap:60 FINAL <ls_f> (row of lt_fin) assigned",
            "zcl_s.clas.abap:62 FINAL lt_fin is FINAL, changed",
            "zcl_s.clas.abap:63 FINAL lt_fin is FINAL, assigned",
        ])
        self.assertEqual(rc, 18)
        self.assertIn("3 keyed types", out)
        self.assertIn("7 row handles", out)


class SortedRowsFileFilter(unittest.TestCase):

    def test_file_narrows_the_report_not_the_types(self):
        """Keyed types and signatures are package-wide: `--file` selects which
        files are reported, never which declarations are known. Read through
        the narrowed corpus, a row of a type declared in another file was
        nobody's key, and the write through it went unreported."""
        p = project({
            "src/zif_t.intf.abap": """
                INTERFACE zif_t PUBLIC.
                  TYPES mty_rows TYPE SORTED TABLE OF mty_row WITH UNIQUE KEY id.
                ENDINTERFACE.
                """,
            "src/zcl_u.clas.abap": """
                CLASS zcl_u IMPLEMENTATION.
                  METHOD m.
                    DATA lt_rows TYPE zif_t=>mty_rows.
                    LOOP AT lt_rows ASSIGNING FIELD-SYMBOL(<ls>).
                      <ls>-id = 1.
                    ENDLOOP.
                  ENDMETHOD.
                ENDCLASS.
                """,
            "src/zcl_v.clas.abap": """
                CLASS zcl_v IMPLEMENTATION.
                  METHOD m.
                    DATA lt_rows TYPE zif_t=>mty_rows.
                    LOOP AT lt_rows ASSIGNING FIELD-SYMBOL(<ls>).
                      <ls>-id = 2.
                    ENDLOOP.
                  ENDMETHOD.
                ENDCLASS.
                """})
        _, out = p.run("check_sorted_rows.py", "--file", "zcl_u")
        p.close()
        self.assertEqual([f.split("|")[0].split()[0] for f in crosses(out)], ["zcl_u.clas.abap:5"])
        self.assertIn("1 keyed types", out)


class ModelWriters(unittest.TestCase):

    def test_unwritten(self):
        p = project({
            "src/zif_m.intf.abap": """
                INTERFACE zif_m PUBLIC.
                  TYPES: BEGIN OF mty_doc,
                           filled TYPE i,
                           forgotten TYPE i,
                         END OF mty_doc.
                ENDINTERFACE.
                """,
            "src/zcl_w.clas.abap": "CLASS zcl_w IMPLEMENTATION.\n  METHOD m.\n    rs_doc-filled = 1.\n"
                                   "  ENDMETHOD.\nENDCLASS.\n"},
            '[model]\ninterface = "zif_m"\n')
        _, out = p.run("check_model_writers.py")
        p.close()
        self.assertIn("mty_doc-forgotten: nothing writes it", out)
        self.assertNotIn("mty_doc-filled", out)

    def test_every_structure_form(self):
        """Chained and unchained structures, a nested one, an INCLUDE, two
        members on one line; a constant group and a commented member are no
        fields."""
        p = project({
            "src/zif_m.intf.abap": """
                INTERFACE zif_m PUBLIC.
                  CONSTANTS:
                    BEGIN OF mc_kind,
                      a TYPE c LENGTH 1 VALUE 'A',
                    END OF mc_kind.
                  TYPES: BEGIN OF mty_head,
                           id TYPE i,
                           ref TYPE REF TO zcl_x,
                           BEGIN OF inner,
                             deep TYPE i,
                           END OF inner,
                         END OF mty_head.
                  TYPES BEGIN OF mty_inc.
                  INCLUDE TYPE mty_head.
                  TYPES extra TYPE i.
                  TYPES END OF mty_inc.
                  TYPES: BEGIN OF mty_pair,
                           left TYPE i, right TYPE i,
                           " gone TYPE i,
                         END OF mty_pair.
                ENDINTERFACE.
                """,
            "src/zcl_w.clas.abap": """
                CLASS zcl_w IMPLEMENTATION.
                  METHOD m.
                    rs_head-id = 1.
                    rs_head-inner-deep = 2.
                    <ls_inc>-extra = 3.
                    DATA(ls_pair) = VALUE zif_m=>mty_pair( left = 1 ).
                  ENDMETHOD.
                ENDCLASS.
                """}, '[model]\ninterface = "zif_m"\n')
        _, out = p.run("check_model_writers.py")
        p.close()
        self.assertEqual(crosses(out), ["mty_head-ref: nothing writes it",
                                        "mty_pair-right: nothing writes it"])
        self.assertIn("4 structure(s), 7 field(s) in zif_m", out)
        self.assertIn("PROBABLE, by field name only: mty_pair-left [zcl_w.clas.abap]", out)


class SuppressionKeys(SuppressionAsserts, unittest.TestCase):
    """Each finding is excused by the key its docs name."""

    def test_sorted_rows_and_per_file(self):
        p = project({"src/zcl_s.clas.abap": """
            CLASS zcl_s IMPLEMENTATION.
              METHOD m.
                TYPES mty_rows TYPE SORTED TABLE OF mty_row WITH UNIQUE KEY id.
                DATA lt_rows TYPE mty_rows.
                LOOP AT lt_rows ASSIGNING FIELD-SYMBOL(<ls_row>).
                  <ls_row>-id = 1.
                ENDLOOP.
                IF is_x( ).
                ENDIF.
                rs_item-reason = iv_reason.
                rs_item = _mo_engine->read( ).
              ENDMETHOD.
            ENDCLASS.
            """}, """
            [suppress.sorted_rows.keyedrows]
            'zcl_s.clas.abap:6 KEY' = "looked"
            [suppress.bare_bool.barebool]
            'zcl_s.clas.abap:8' = "looked"
            [suppress.clobbered.clobbered]
            'zcl_s.clas.abap:11 rs_item-reason' = "looked"
            """)
        outs = [p.run(s)[1] for s in ("check_sorted_rows.py", "check_bare_bool.py",
                                      "check_clobbered_writes.py")]
        p.close()
        self.assert_excused(outs[0], [("keyedrows", "zcl_s.clas.abap:6 KEY", "<ls_row>-id (row")])
        self.assert_excused(outs[1], [("barebool", "zcl_s.clas.abap:8", "IF is_x")])
        self.assert_excused(outs[2], [("clobbered", "zcl_s.clas.abap:11 rs_item-reason", "written at line")])


if __name__ == "__main__":
    unittest.main(verbosity=1)
