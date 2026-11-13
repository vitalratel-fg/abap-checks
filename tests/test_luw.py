#!/usr/bin/env python3
"""check_luw.py: who may close the LUW, and who chooses it."""

import unittest

from _project import SuppressionAsserts, crosses, fixture, project


class Luw(unittest.TestCase):

    def test_commit_owner_and_inject(self):
        cfg = '''
            [luw]
            owners = ["zcl_luw"]

            [luw.inject]
            interface = "zif_luw"
            builds = "zcl_\\\\w+"
            forwarders = "_service$"
            '''
        aware = """
            CLASS zcl_{n} DEFINITION PUBLIC.
              PUBLIC SECTION.
                METHODS constructor IMPORTING io_luw TYPE REF TO zif_luw.
            ENDCLASS.
            CLASS zcl_{n} IMPLEMENTATION.
              METHOD constructor.
              ENDMETHOD.
            ENDCLASS.
            """
        p = project({
            "src/zcl_luw.clas.abap": "CLASS zcl_luw DEFINITION PUBLIC.\nENDCLASS.\nCLASS zcl_luw IMPLEMENTATION.\n"
                                     "  METHOD save.\n    COMMIT WORK AND WAIT.\n  ENDMETHOD.\nENDCLASS.\n",
            "src/zcl_rogue.clas.abap": "CLASS zcl_rogue DEFINITION PUBLIC.\nENDCLASS.\nCLASS zcl_rogue IMPLEMENTATION.\n"
                                       "  METHOD save.\n    COMMIT WORK.\n  ENDMETHOD.\nENDCLASS.\n",
            "src/zcl_repo.clas.abap": aware.replace("{n}", "repo"),
            "src/zcl_other.clas.abap": aware.replace("{n}", "other"),
            "src/zcl_x_service.clas.abap": """
                CLASS zcl_x_service DEFINITION PUBLIC.
                ENDCLASS.
                CLASS zcl_x_service IMPLEMENTATION.
                  METHOD build.
                    DATA(lo) = NEW zcl_repo( io_luw = lo_luw ).
                    DATA(lo2) = NEW zcl_other( ).
                  ENDMETHOD.
                ENDCLASS.
                """}, cfg)
        _, out = p.run("check_luw.py")
        p.close()
        self.assertIn("zcl_rogue.clas.abap:5  COMMIT WORK", out)
        self.assertNotIn("zcl_luw.clas.abap", out)
        self.assertIn("HIDDEN   zcl_x_service.clas.abap", out)
        self.assertIn("SPLIT    zcl_x_service.clas.abap  build: zcl_repo=lo_luw, zcl_other=none", out)
        self.assertIn("--   sync", out)


class LuwFixture(unittest.TestCase):
    """tests/fixtures/messages_luw: LUW ownership."""

    @classmethod
    def setUpClass(cls):
        p = fixture("messages_luw")
        cls.luw_rc, cls.luw = p.run("check_luw.py")
        p.close()

    def test_commit_and_sync(self):
        found = crosses(self.luw)
        self.assertEqual(found[:4], [
            "zcl_sync.clas.abap:6  'BAPI_TRANSACTION_COMMIT'",
            "zcl_unit.clas.abap:6  COMMIT ENTITIES",
            "zcl_unit.clas.locals_imp.abap:3  ROLLBACK WORK",
            "zcl_sync.clas.abap:4  ZCL_SYNC~RAISE names SAP_WAPI_CREATE_EVENT, which commits unless told not to",
        ])

    def test_inject_reads_the_constructor_and_every_include(self):
        """A method other than the constructor taking the LUW does not make a
        class LUW-aware, and a local helper that builds a collaborator is the
        class building it."""
        self.assertEqual(crosses(self.luw)[4:], [
            "DROPPED  zcl_a_service.clas.abap:12  zcl_a_service builds zcl_repo without passing IO_LUW on",
            "SPLIT    zcl_a_service.clas.abap  build: zcl_repo=_mo_luw, zcl_store=_mo_other, zcl_repo=none",
            "HIDDEN   zcl_b_service.clas.abap:8  zcl_b_service builds zcl_repo but takes no IO_LUW of its own",
            "HIDDEN   zcl_b_service.clas.locals_imp.abap:3  zcl_b_service builds zcl_store but takes "
            "no IO_LUW of its own",
        ])
        self.assertIn("3 LUW-aware class(es): zcl_a_service, zcl_repo, zcl_store", self.luw)


class SuppressionKeys(SuppressionAsserts, unittest.TestCase):
    """Each finding is excused by the key its docs name."""

    def test_luw(self):
        entries = [
            ("luw", "commit", "zcl_unit.clas.abap:6", "✗ zcl_unit.clas.abap:6"),
            ("luw", "sync", "zcl_sync~raise:sap_wapi_create_event", "names SAP_WAPI"),
            ("luw", "inject", "zcl_b_service->zcl_repo", "builds zcl_repo but"),
        ]
        out = self.run_fixture("messages_luw", entries, "check_luw.py")["check_luw.py"]
        self.assert_excused(out, [e[1:] for e in entries])


if __name__ == "__main__":
    unittest.main(verbosity=1)
