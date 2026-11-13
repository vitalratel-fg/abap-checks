#!/usr/bin/env python3
"""check_messages.py: message classes reconciled, and the buffer rules."""

import unittest

from _project import SuppressionAsserts, crosses, fixture, project


class Messages(unittest.TestCase):

    def test_reconciliation(self):
        cfg = '''
            [[meta.msgclass]]
            name = "ZX"
            text = "X"
            messages = [["001", "One &1"], ["002", "Never raised"], ["003", "Two &1 &2"]]
            [meta.classes]
            zcl_m = "Raises"
            '''
        p = project({"src/zcl_m.clas.abap": """
            CLASS zcl_m DEFINITION PUBLIC.
            ENDCLASS.
            CLASS zcl_m IMPLEMENTATION.
              METHOD m.
                MESSAGE e001(zx) WITH lv_a.
                MESSAGE w001(zx) WITH lv_a lv_b.
                MESSAGE e003(zx) WITH lv_a.
                MESSAGE e009(zx).
              ENDMETHOD.
            ENDCLASS.
            """}, cfg)
        rc, out = p.run("make_meta.py")
        self.assertEqual(rc, 0, out)
        _, out = p.run("check_messages.py")
        p.close()
        self.assertIn("zx 009 raised at", out)
        self.assertIn("zx 002 defined in zx.msag.xml, raised nowhere", out)
        self.assertIn("zx 001 raised with [1, 2] operands", out)
        self.assertIn("zx 003 text has 2 slot(s), raised with 1 operand(s)", out)
        self.assertIn("--   buffer", out)


class MessagesFixture(unittest.TestCase):
    """tests/fixtures/messages_luw: reconciliation and the buffer rules."""

    @classmethod
    def setUpClass(cls):
        p = fixture("messages_luw")
        rc, out = p.run("make_meta.py")
        assert rc == 0, out
        cls.msg_rc, cls.msg = p.run("check_messages.py")
        p.close()

    def test_messages(self):
        self.assertEqual(crosses(self.msg), [
            "zx 009 raised at zcl_msg.clas.abap:23, not in zx.msag.xml and not pre-existing",
            "zx 001 raised with [1, 2] operands as e/w -- one T100 text cannot serve both: "
            "zcl_msg.clas.abap:20, zcl_msg.clas.abap:21",
            "zx 001 text has 1 slot(s), raised with 2 operand(s) at zcl_msg.clas.abap:20",
            "zx 002 text has 2 slot(s), raised with 1 operand(s) at zcl_msg.clas.abap:22",
            "zcl_msg: takes IO_MSG and exports ET_MESSAGES - a caller can alias the buffer it also gets back",
            "zcl_msg~run exports the buffer at the end and can leave before it: 'RETURN.'",
            "zcl_msg~checked exports the buffer at the end and can leave before it: "
            "'CHECK lv_x IS NOT INITIAL.'",
        ])
        self.assertIn("1 dynamic MESSAGE ID site(s)", self.msg)
        self.assertIn("1 number(s) held in a T100 text-id constant, invisible to SE91 where-used, "
                      "ATC and `arity`: zcl_collect.clas.abap:4 MC_NOT_FOUND = zx 002", self.msg)
        self.assertIn("1 collector(s), 0 service(s)", self.msg)
        self.assertIn("3 exporting method(s) scanned", self.msg)


class MessageClassFile(unittest.TestCase):
    def test_malformed_message_class_names_the_file(self):
        p = project({"src/zx.msag.xml": "<a></a>junk",
                     "src/zcl_m.clas.abap": "CLASS zcl_m IMPLEMENTATION.\nENDCLASS.\n"})
        rc, out = p.run("check_messages.py")
        p.close()
        self.assertEqual(rc, 1)
        self.assertIn("zx.msag.xml: not well-formed XML", out)
        self.assertNotIn("Traceback", out)


class SuppressionKeys(SuppressionAsserts, unittest.TestCase):
    """Each finding is excused by the key its docs name."""

    def test_messages(self):
        entries = [
            ("messages", "missing", "zx 009", "✗ zx 009"),
            ("messages", "arity", "zx 001", "operands as e/w"),
            ("messages", "placeholder", "zx 002", "✗ zx 002 text"),
            ("messages", "buffer", "zcl_msg", "✗ zcl_msg: takes"),
            ("messages", "export", "zcl_msg~checked", "✗ zcl_msg~checked"),
        ]
        out = self.run_fixture("messages_luw", entries, "check_messages.py",
                               before=["make_meta.py"])["check_messages.py"]
        self.assert_excused(out, [e[1:] for e in entries])


if __name__ == "__main__":
    unittest.main(verbosity=1)
