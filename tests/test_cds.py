#!/usr/bin/env python3
"""check_cds.py and cds_sources.py: the CDS rules and the source count."""

import unittest

from _project import SuppressionAsserts, crosses, fixture, project


class Cds(unittest.TestCase):

    def test_rules(self):
        view = """
            @AccessControl.authorizationCheck: #NOT_REQUIRED
            define view entity ZI_X as select distinct from ztab as a
              left outer to one join ztab2 as b on a.k = b.k or a.k = a.k
            {
              key a.k as K,
                  case a.f when 'A' then 1 end as F,
              key a.g as G
            }
            """
        p = project({"src/zi_x.ddls.asddls": view},
                    '[checks]\noff = ["cds.distinct"]\n')
        _, out = p.run("check_cds.py")
        p.close()
        self.assertIn("--   distinct", out)
        self.assertIn("zi_x: OR in ON condition", out)
        self.assertIn("compares a field with itself", out)
        self.assertIn("CASE without ELSE", out)
        self.assertIn("key G after non-key F", out)
        self.assertIn("to one ztab2 as b: its key is unknown", out)
        self.assertIn("--   budget", out)


class CdsRules(unittest.TestCase):

    def test_all_thirty_rules(self):
        """Every rule fires on the view written to break it, and stays silent
        on its neighbours: a to-one association binding the whole key
        (zc_bare), a view within budget (zi_twice), a filter field that is a
        plain column down to a table (zc_view.companycode)."""
        p = fixture("cds")
        rc, out = p.run("check_cds.py")
        p.close()
        unknown = "its key is unknown; add it to [cds.keys] (from SE11)"
        self.assertEqual(crosses(out), [
            "zi_classic: classic DDIC-based view; define a view entity",
            "zi_tf: table function",
            "zi_classic: SELECT DISTINCT",
            "zi_joins: OR in ON condition: t.a = o.k or t.b = o.k",
            "zi_joins: s.k = s.k compares a field with itself",
            "zi_joins: inner join without cardinality",
            "zi_joins: association without cardinality in words: "
            "association to zt_three as _Free on _Free.k = o.k",
            "zi_joins: cross join",
            "zi_joins: right outer join",
            "zi_misc: window function (OVER)",
            "zi_misc (ddls): names legacy object ZV_OLD_STUFF",
            "zi_ghost: exposed, but no data definition on disk",
            "zi_twice: exposed, authorizationCheck is not #CHECK",
            "zi_classic: #CHECK and no access control ZI_CLASSIC",
            "zi_lonely: access control for a view that is not on disk",
            "zc_bare: consumption view without @Metadata.allowExtensions: true",
            "zc_bare: consumption view without metadata extension",
            "zc_view: @UI annotation in the data definition; move it to the extension",
            "zc_view: consumption view without @Metadata.allowExtensions: true",
            "bad_name: data definition outside /z[ic]_/",
            "zs_a_service_name_longer_than_30: longer than 30 characters",
            "zi_misc: reads ACDOCA in the request path",
            "zi_joins: LIKE in ON condition: l.k like ''",
            "zi_joins: zt_one read 2 times in one branch",
            "zi_joins: zt_three read 3 times in one branch",
            "zi_twice: zt_one read 2 times in one branch",
            "zi_misc: slot family amt1,2",
            "zc_view: 3 data-source references, budget 2",
            "zc_bare: filter field plant: zc_bare.plant comes through association _Tw",
            "zi_custom: custom entity",
            "zi_custom: virtual element",
            "zcl_amdp.clas.abap: AMDP",
            "zi_entity: behaviour definition",
            "zi_misc: AND and OR at one level: "
            "a.x = '' and a.y = '' or a.z = '' and (a.q <> '' or a.q <> '')",
            "zi_misc: `a.q != … or a.q != …` is always true",
            "zi_joins: join zt_one as s on its own fields and constants only",
            "zi_joins: join zt_three as l on its own fields and constants only",
            "zi_misc: join zt_one as c on its own fields and constants only",
            "zi_misc: key Amt is an amount, a quantity or ABS()",
            "zi_twice: annotation names _Ghost, which is not defined",
            "zc_bare: element plant is not CamelCase",
            "zc_view: element companycode is not CamelCase",
            "zc_view: element plain_name is not CamelCase",
            "zc_view: to one zi_twice as _one leaves key g unbound",
            f"zi_joins: to one zt_one as s: {unknown}",
            f"zi_joins: to one zt_three as l: {unknown}",
            f"zi_misc: to one zv_old_stuff as v: {unknown}",
            f"zi_misc: to one zt_one as c: {unknown}",
            "zi_toone: to one zt_two as t leaves key b unbound",
            f"zi_toone: to one zt_unknown as u: {unknown}",
            "zi_toone: to one zi_twice as _twice leaves key g unbound",
            f"zi_twice: to one zt_one as b: {unknown}",
            "zc_view: role named zc_other, not as its file",
            "zc_view: grants on ZI_TOONE, not on its own view",
            "zc_view: restricts by bukrs, which ZC_VIEW does not have",
            "zc_view: pfcg_auth without ACTVT = '03'",
            "zi_lonely: grants on ZI_LONELY without a pfcg_auth condition",
            "zc_bare: no element companycode, a mandatory filter",
            "zc_view: companycode is not a mandatory filter",
            "zc_view: table section on to-one _One; use #FIELDGROUP_REFERENCE",
            "zi_twice:8: CASE without ELSE: case a.f when '' then 1 end",
            "zi_twice: key G after non-key F",
        ])
        self.assertEqual(rc, 62)
        self.assertNotIn("--", out.split("ok   suppressions")[0])


class BaseColumns(unittest.TestCase):

    def test_every_way_a_filter_field_stops_being_a_column(self):
        p = project({
            "src/zc_expr.ddls.asddls": "define view entity zc_expr as select from zt as a "
                                       "{ key a.k as K, concat(a.x, a.y) as plant }",
            "src/zc_union.ddls.asddls": "define view entity zc_union as select from zt as a "
                                        "{ key a.k as K, a.plant as plant } union select from zt2 as b "
                                        "{ key b.k as K }",
            "src/zc_alias.ddls.asddls": "define view entity zc_alias as select from zt as a "
                                        "{ key a.k as K, q.plant as plant }",
            "src/zi_tf.ddls.asddls": "define table function zi_tf returns { plant : abap.char(4); } "
                                     "implemented by method zcl_tf=>run;",
            "src/zc_tf.ddls.asddls": "define view entity zc_tf as select from zi_tf as t "
                                     "{ key t.plant as plant }",
            "src/zi_mid.ddls.asddls": "define view entity zi_mid as select from zt as m "
                                      "association of many to one zt3 as _Plant on _Plant.k = m.k "
                                      "{ key m.k as K, _Plant.plant as plant, _Plant }",
            "src/zc_deep.ddls.asddls": "define view entity zc_deep as select from zi_mid as d "
                                       "{ key d.K as K, d.plant as plant }",
            "src/zc_fine.ddls.asddls": "define view entity zc_fine as select from zt as a "
                                       "{ key a.k as K, a.plant as plant }",
        }, '[cds]\nconsumption = "zc_"\nfilter_fields = ["plant"]\n')
        _, out = p.run("check_cds.py", "basecol")
        p.close()
        self.assertEqual(crosses(out), [
            "zc_alias: filter field plant: zc_alias.plant: alias q not resolved",
            "zc_deep: filter field plant: zi_mid.plant comes through association _Plant",
            "zc_expr: filter field plant: zc_expr.plant is `concat(a.x, a.y)`",
            "zc_tf: filter field plant: zc_tf.plant comes from table function zi_tf: a barrier",
            "zc_union: filter field plant: zc_union.plant: not in every branch",
        ])


class CdsSources(unittest.TestCase):

    def test_counts_through_views_and_amdp_bodies(self):
        """Views expand to their sources; a table function to the sources its
        AMDP body reads from its USING list. Comments, literals and sources
        outside USING are not counted."""
        p = project({
            "src/zc_top.ddls.asddls": """
                define view entity ZC_TOP as select from ZI_A as a
                  inner join ZI_TF as f on f.k = a.k
                  // join zt_commented as c
                { key a.k as K }
                """,
            "src/zi_a.ddls.asddls": """
                define view entity ZI_A as select from zt1 as x
                  inner join zt1 as y on y.k = x.k
                { key x.k as K, 'join zt_literal' as L }
                """,
            "src/zi_tf.ddls.asddls":
                "define table function ZI_TF returns { k : abap.char(1); } implemented by method zcl_tf=>run;",
            "src/zcl_tf.clas.abap": """
                CLASS zcl_tf IMPLEMENTATION.
                  METHOD run BY DATABASE FUNCTION FOR HDB LANGUAGE SQLSCRIPT
                    OPTIONS READ-ONLY FOR TABLE FUNCTION zi_tf USING zt2 zt3.
                    -- from zt_comment
                    RETURN SELECT 'Extract Data from MBEW' AS k FROM zt2 JOIN zt3 ON zt3.k = zt2.k
                      JOIN zt_unlisted ON 1 = 1;
                  ENDMETHOD.
                ENDCLASS.
                """})
        rc, out = p.run("cds_sources.py", "zc_top", "zi_tf", "zi_nothing")
        no_args, _ = p.run("cds_sources.py")
        # Copies pasted from ADT, read from folders of their own.
        for name in ("zc_top.ddls.asddls", "zi_a.ddls.asddls", "zi_tf.ddls.asddls"):
            (p.root / "legacy/views").mkdir(parents=True, exist_ok=True)
            (p.root / "legacy/views" / name.replace(".ddls.asddls", ".txt")).write_text(
                (p.root / "src" / name).read_text())
        (p.root / "legacy/classes").mkdir(parents=True)
        (p.root / "src/zcl_tf.clas.abap").rename(p.root / "legacy/classes/zcl_tf.txt")
        _, pasted = p.run("cds_sources.py", "--views", "legacy/views", "--amdp", "legacy/classes", "zc_top")
        p.close()
        self.assertEqual([" ".join(l.split()) for l in pasted.splitlines()],
                         ["ZC_TOP: 4 data-source references", "2 ZT1", "1 ZT2", "1 ZT3"])
        self.assertEqual(rc, 0)
        self.assertEqual(no_args, 2)
        self.assertEqual([" ".join(l.split()) for l in out.splitlines()], [
            "ZC_TOP: 4 data-source references", "2 ZT1", "1 ZT2", "1 ZT3",
            "ZI_TF: 2 data-source references", "1 ZT2", "1 ZT3",
            "ZI_NOTHING: not among 3 view(s) read from the package",
        ])


class SuppressionKeys(SuppressionAsserts, unittest.TestCase):
    """Each finding is excused by the key its docs name."""

    def test_cds(self):
        entries = [
            ("legacy", "zi_misc:ZV_OLD_STUFF", "names legacy object"),
            ("dcl", "zi_twice:mode", "zi_twice: exposed"),
            ("dcl", "zi_classic:role", "#CHECK and no access control"),
            ("dcl", "zi_lonely:orphan", "for a view that is not on disk"),
            ("mde", "zc_view:ui", "@UI annotation in the data definition"),
            ("names", "bad_name", "bad_name: data definition"),
            ("sources", "zi_misc:acdoca", "reads ACDOCA"),
            ("repeat", "zi_twice:zt_one", "zi_twice: zt_one read"),
            ("slots", "zi_misc:amt", "slot family"),
            ("budget", "zc_view", "budget 2"),
            ("basecol", "zc_bare:plant", "filter field plant"),
            ("abapfree", "zcl_amdp.clas.abap", "zcl_amdp.clas.abap: AMDP"),
            ("constjoin", "zi_misc:c", "join zt_one as c on"),
            ("elements", "zc_bare:plant", "element plant is not"),
            ("toone", "zi_toone:t:b", "zt_two as t leaves"),
            ("toone", "zi_toone:u:?", "zt_unknown as u"),
            ("dclgrant", "zi_lonely", "grants on ZI_LONELY"),
            ("mandatory", "zc_bare:companycode", "no element companycode"),
            ("caseelse", "zi_twice:8", "CASE without ELSE"),
            ("keyfirst", "zi_twice:g", "key G after"),
        ]
        out = self.run_fixture("cds", [("cds", *e) for e in entries], "check_cds.py")["check_cds.py"]
        self.assert_excused(out, entries)


if __name__ == "__main__":
    unittest.main(verbosity=1)
