#!/usr/bin/env python3
"""check_standing.py: the hygiene any package keeps."""

import unittest

from _project import CLASS, IFACE, SuppressionAsserts, crosses, fixture, project


class Standing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.p = project({"src/zif_a.intf.abap": IFACE, "src/zcl_a.clas.abap": CLASS},
                        '[package]\nown = "z[a-z]{2}_\\\\w+"\nobjects = "zc[lx]_\\\\w+|zif_\\\\w+"\n')
        cls.rc, cls.out = cls.p.run("check_standing.py")

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def hit(self, text):
        self.assertIn(text, self.out)

    def test_orphan(self):
        self.hit("✗ zif_a.unused")

    def test_deadprivate_but_not_constructor(self):
        self.hit("✗ zcl_a._dead")
        self.assertNotIn("zcl_a.constructor", self.out)
        self.assertNotIn("zcl_a._used", self.out)

    def test_writeonly(self):
        self.hit("zcl_a: _MV_LOST is assigned and never read")
        self.assertNotIn("_MV_KEPT is assigned", self.out)

    def test_loops(self):
        self.hit("LOOP AT lt_rows INTO - use ASSIGNING")

    def test_typenames(self):
        self.hit("zcl_a: ty_bad is public, expected mty_*")
        self.assertNotIn("mty_x is public", self.out)

    def test_methodnames_spare_constructor(self):
        self.hit("zcl_a->unprefixed is private, expected _*")
        self.assertNotIn("->constructor", self.out)

    def test_qualified_reads_code_not_comments(self):
        self.hit("zif_a=>missing in zcl_a")
        self.assertNotIn("zif_b=>nothing", self.out)

    def test_renamed_needs_config(self):
        self.assertIn("--   renamed", self.out)

    def test_exit_code_counts_findings(self):
        self.assertEqual(self.rc, int(self.out.strip().split()[-2]))


class StandingMore(unittest.TestCase):

    def test_graph_cycle(self):
        p = project({"src/zif_p.intf.abap": "INTERFACE zif_p PUBLIC.\n  DATA x TYPE REF TO zif_q.\nENDINTERFACE.\n",
                     "src/zif_q.intf.abap": "INTERFACE zif_q PUBLIC.\n  DATA y TYPE REF TO zif_p.\nENDINTERFACE.\n"})
        _, out = p.run("check_standing.py", "graph")
        p.close()
        self.assertIn("✗ zif_p", out)

    def test_impls_and_undrafted(self):
        p = project({"src/zif_a.intf.abap": IFACE,
                     "src/zcl_b.clas.abap": """
                        CLASS zcl_b DEFINITION PUBLIC.
                          PUBLIC SECTION.
                            INTERFACES zif_a.
                            DATA mo_x TYPE REF TO zcl_gone.
                        ENDCLASS.
                        CLASS zcl_b IMPLEMENTATION.
                          METHOD zif_a~run.
                          ENDMETHOD.
                        ENDCLASS.
                        """},
                    '[package]\nobjects = "zcl_\\\\w+"\n')
        _, out = p.run("check_standing.py", "impls", "undrafted")
        p.close()
        self.assertIn("zcl_b: zif_a~unused", out)
        self.assertIn("✗ zcl_gone", out)

    def test_renamed(self):
        p = project({"src/zcl_c.clas.abap": "CLASS zcl_c DEFINITION PUBLIC.\n  "
                     "\" old name zcl_legacy_thing\nENDCLASS.\n"},
                    "[naming]\nretired = ['\\bzcl_legacy_thing\\b']\n")
        _, out = p.run("check_standing.py", "renamed")
        p.close()
        self.assertIn("in zcl_c", out)

    def test_raising(self):
        p = project({"src/zif_r.intf.abap": "INTERFACE zif_r PUBLIC.\n  METHODS go RAISING zcx_x.\nENDINTERFACE.\n",
                     "src/zcl_r.clas.abap": """
                        CLASS zcl_r DEFINITION PUBLIC.
                          PUBLIC SECTION.
                            METHODS caller.
                            METHODS safe.
                          PRIVATE SECTION.
                            DATA _mo_r TYPE REF TO zif_r.
                        ENDCLASS.
                        CLASS zcl_r IMPLEMENTATION.
                          METHOD caller.
                            _mo_r->go( ).
                          ENDMETHOD.
                          METHOD safe.
                            TRY.
                                _mo_r->go( ).
                              CATCH zcx_x.
                            ENDTRY.
                          ENDMETHOD.
                        ENDCLASS.
                        """})
        _, out = p.run("check_standing.py", "raising")
        p.close()
        self.assertIn("zcl_r~caller", out)
        self.assertNotIn("zcl_r~safe", out)


class MethodNames(unittest.TestCase):

    def test_every_class_of_the_file_but_tests(self):
        """Local classes count, test classes and DEFERRED / LOCAL FRIENDS lines
        do not; constructors and redefinitions keep their names."""
        p = project({
            "src/zcl_m.clas.abap": """
                CLASS zcl_m DEFINITION PUBLIC.
                  PUBLIC SECTION.
                    METHODS run.
                    METHODS _leaked.
                    CLASS-METHODS make RETURNING VALUE(ro) TYPE REF TO zcl_m.
                    METHODS class_constructor.
                  PROTECTED SECTION.
                    METHODS shown.
                    METHODS _kept.
                    METHODS base REDEFINITION.
                  PRIVATE SECTION.
                    METHODS: _a, b.
                ENDCLASS.
                CLASS zcl_m IMPLEMENTATION.
                ENDCLASS.
                """,
            "src/zcl_m.clas.locals_imp.abap": """
                CLASS lcl_help DEFINITION DEFERRED.
                CLASS zcl_m DEFINITION LOCAL FRIENDS lcl_help.
                CLASS lcl_help DEFINITION.
                  PUBLIC SECTION.
                    METHODS _wrong.
                  PRIVATE SECTION.
                    METHODS bare.
                ENDCLASS.
                """,
            "src/zcl_m.clas.testclasses.abap": """
                CLASS ltc_m DEFINITION FOR TESTING RISK LEVEL HARMLESS DURATION SHORT.
                  PRIVATE SECTION.
                    METHODS runs FOR TESTING.
                ENDCLASS.
                """}, '[naming]\nmethod_private = "_"\n')
        _, out = p.run("check_standing.py", "methodnames")
        p.close()
        self.assertEqual(crosses(out), [
            "zcl_m: lcl_help->_wrong is public, expected no _",
            "zcl_m: lcl_help->bare is private, expected _*",
            "zcl_m: zcl_m->_leaked is public, expected no _",
            "zcl_m: zcl_m->b is private, expected _*",
            "zcl_m: zcl_m->shown is protected, expected _*",
        ])
        self.assertIn("9 method declaration(s) scanned, 1 test class(es) skipped", out)


class StandingFixture(unittest.TestCase):
    """Every standing check over one package, tests/fixtures/standing."""

    @classmethod
    def setUpClass(cls):
        p = fixture("standing")
        cls.rc, cls.out = p.run("check_standing.py")
        p.close()

    def check(self, name):
        """The findings one check printed."""
        section = self.out.split(f" {name} ", 1)[1].split("\nFAIL ")[0].split("\nok ")[0]
        return crosses(section.split("\n--")[0])

    def test_undrafted(self):
        self.assertEqual(self.check("undrafted"), ["zcl_missing", "zcl_not_there", "zcx_a"])

    def test_raising_spares_a_caught_call_and_a_declared_one(self):
        self.assertEqual(self.check("raising"), ["zcl_user~go"])

    def test_qualified_reads_the_declaration_part_only(self):
        """`lv_local` is declared inside a method: not a member of the class."""
        self.assertEqual(self.check("qualified"),
                         ["zcl_user=>lv_local in zcl_user", "zif_a=>missing in zcl_user"])
        self.assertIn("5 qualified reference(s) across 14 objects", self.out)

    def test_typenames_skip_components_and_read_a_programs_local_class(self):
        self.assertEqual(self.check("typenames"), [
            "zcl_user: mty_wrong is protected, expected _mty_*",
            "zcl_user: ty_public is public, expected mty_*",
            "zif_a: bad_type is public, expected mty_*",
            "zr_prog: ty_loc is public, expected mty_*",
        ])
        self.assertIn("8 type declaration(s) scanned", self.out)

    def test_methodnames(self):
        self.assertEqual(self.check("methodnames"),
                         ["zcl_user: zcl_user->setup is private, expected _*"])
        self.assertIn("9 method declaration(s) scanned, 0 test class(es) skipped", self.out)

    def test_orphans_typed_qualified_through_a_class_and_by_name(self):
        self.assertEqual(self.check("orphans"),
                         ["zif_a.quiet", "zif_o.never", "zif_p.a", "zif_p.b", "zif_q.needs"])
        self.assertIn("3 method(s) credited by NAME only", self.out)

    def test_impls_honour_abstract_classes_and_their_own_ancestry(self):
        """An indented ABSTRACT class defers like any other, and a local class
        inheriting from one is not the global class's parent."""
        self.assertEqual(self.check("impls"), [
            "zcl_all_child: zif_p~b  (deferred by an ancestor - this concrete class owes it)",
            "zcl_concrete: zif_p~b  (deferred by an ancestor - this concrete class owes it)",
            "zcl_impl_o: zif_q~needs",
        ])
        self.assertIn("9 classes, 7 interface contract(s)", self.out)
        self.assertIn("abstract, deferral honoured: ['zcl_abs', 'zcl_all', 'zcl_base']", self.out)

    def test_deadprivate_spares_framework_methods(self):
        self.assertEqual(self.check("deadprivate"), ["zcl_user._caught", "zcl_user._dead"])

    def test_writeonly(self):
        self.assertEqual(self.check("writeonly"), [
            "zcl_user: _MV_LOST is assigned and never read",
            "zr_prog: _MV_ONLY_SET is assigned and never read",
        ])
        self.assertIn("5 private field(s) scanned", self.out)

    def test_deadconst_reads_members_with_a_length(self):
        """A group typed `c LENGTH 1`, backed by no domain, is the case the
        check exists for."""
        self.assertEqual(self.check("deadconst"), [
            "zcl_user: _mc_kind-dead declared, named nowhere",
            "zif_a: mc_dead declared, named nowhere",
        ])
        self.assertIn("4 constant(s) checked", self.out)

    def test_ddic_and_names_and_renamed(self):
        self.assertEqual(self.check("ddic"), ["zcl_user: TYPE zcl_not_there resolves to nothing on disk"])
        self.assertEqual(self.check("names"), ["zcl_a_name_that_is_far_too_long_x (33 > 30)"])
        self.assertEqual(self.check("renamed"), ["\\bzcl_old\\b in docs/notes.md"])


class Chains(unittest.TestCase):
    def test_a_chain_declares_every_member(self):
        """`DATA:`, `CONSTANTS:`, `INTERFACES:` and `METHODS:` chains declare
        each of their members, wherever a check reads them."""
        p = project({
            "src/zif_x.intf.abap": "INTERFACE zif_x PUBLIC.\n  METHODS a.\nENDINTERFACE.\n",
            "src/zif_y.intf.abap": "INTERFACE zif_y PUBLIC.\n  METHODS b RAISING zcx_y.\nENDINTERFACE.\n",
            "src/zcl_c.clas.abap": """
                CLASS zcl_c DEFINITION PUBLIC.
                  PUBLIC SECTION.
                    INTERFACES: zif_x, zif_y.
                    CONSTANTS: mc_one TYPE i VALUE 1,
                               mc_two TYPE i VALUE 2.
                  PRIVATE SECTION.
                    DATA: _mv_a TYPE i,
                          _mv_b TYPE i.
                    DATA _mo_y TYPE REF TO zif_y.
                    METHODS: _go, _other.
                ENDCLASS.
                CLASS zcl_c IMPLEMENTATION.
                  METHOD zif_x~a.
                    _mv_a = 1.
                    _mv_b = 2.
                    zif_y~b( _mv_a ).
                    DATA(lv) = mc_one.
                  ENDMETHOD.
                  METHOD _go.
                    _mo_y->b( ).
                  ENDMETHOD.
                ENDCLASS.
                """})
        _, out = p.run("check_standing.py", "raising", "impls", "writeonly", "deadconst")
        p.close()
        self.assertEqual(crosses(out), [
            "zcl_c~_go",
            "zcl_c: zif_y~b",
            "zcl_c: _MV_B is assigned and never read",
            "zcl_c: mc_two declared, named nowhere",
        ])


class SuppressionKeys(SuppressionAsserts, unittest.TestCase):
    """Each finding is excused by the key its docs name."""

    def test_standing(self):
        entries = [
            ("standing", "undrafted", "zcx_a", "✗ zcx_a"),
            ("standing", "raising", "zcl_user~go", "✗ zcl_user~go"),
            ("standing", "renamed", r"\bzcl_old\b in docs/notes.md", "✗ \\bzcl_old"),
            ("standing", "qualified", "zif_a=>missing in zcl_user", "✗ zif_a=>missing"),
            ("standing", "names", "zcl_a_name_that_is_far_too_long_x", "✗ zcl_a_name_that"),
            ("standing", "typenames", "zif_a: bad_type is public, expected mty_*", "✗ zif_a: bad_type"),
            ("standing", "methodnames", "zcl_user: zcl_user->setup is private, expected _*", "->setup"),
            ("standing", "orphans", "zif_a.quiet", "✗ zif_a.quiet"),
            ("standing", "impls", "zcl_impl_o.zif_q~needs", "✗ zcl_impl_o: zif_q~needs"),
            ("standing", "deadprivate", "zcl_user._dead", "✗ zcl_user._dead"),
            ("standing", "writeonly", "zcl_user:_MV_LOST", "✗ zcl_user: _MV_LOST"),
            ("standing", "loops", "zcl_user: LOOP AT lt_rows INTO", "✗ zcl_user: LOOP AT"),
            ("standing", "deadconst", "mc_dead", "✗ zif_a: mc_dead"),
            ("standing", "ddic", "zcl_user:zcl_not_there", "✗ zcl_user: TYPE zcl_not_there"),
        ]
        out = self.run_fixture("standing", entries, "check_standing.py")["check_standing.py"]
        self.assert_excused(out, [e[1:] for e in entries])


if __name__ == "__main__":
    unittest.main(verbosity=1)
