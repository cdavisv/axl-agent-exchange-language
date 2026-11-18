import unittest
from unittest.mock import patch
from delta import *
from controls import guarded_control


class GuardControlTests(unittest.TestCase):
    def wires(self):
        before = {"x": 1}
        after = {"x": 2}
        f = frame(before, after, 4, 5)
        return (
            before,
            after,
            {"snapshot": f[:5] + [after], "json_patch": f[:5] + [json_patch_ops(f)]},
        )

    def test_valid_and_target(self):
        before, after, wires = self.wires()
        for mode, f in wires.items():
            self.assertEqual(guarded_control(before, 4, dump(f), mode), after)
            f[4] = "0" * 64
            with self.assertRaisesRegex(Error, "TARGET_MISMATCH"):
                guarded_control(before, 4, dump(f), mode)

    def test_stale_revision_and_hash_before_apply(self):
        before, _, wires = self.wires()
        for mode, f in wires.items():
            with patch(
                "controls.rfc_apply", side_effect=AssertionError("premature apply")
            ) as apply_mock:
                for revision, state in ((3, before), (True, before), (4, {"x": 999})):
                    with self.assertRaisesRegex(Error, "STALE_BASE"):
                        guarded_control(state, revision, dump(f), mode)
                apply_mock.assert_not_called()
            self.assertEqual(before, {"x": 1})

    def test_invalid_patch_not_touched_before_guard(self):
        before, _, wires = self.wires()
        f = wires["json_patch"]
        f[5] = [{"op": "remove", "path": "/missing"}]
        with self.assertRaisesRegex(Error, "STALE_BASE"):
            guarded_control(before, 3, dump(f), "json_patch")
        f[3] = "0" * 64
        with self.assertRaisesRegex(Error, "STALE_BASE"):
            guarded_control(before, 4, dump(f), "json_patch")

    def test_unchanged_revision_cannot_change_state(self):
        before, _, wires = self.wires()
        for mode, f in wires.items():
            f[2] = f[1]
            with self.assertRaisesRegex(Error, "Changed revision"):
                guarded_control(before, 4, dump(f), mode)
        f = wires["json_patch"]
        f[4] = f[3]
        f[5] = [{"op": "add", "path": "/x", "value": 1}]
        with self.assertRaisesRegex(Error, "Changed revision"):
            guarded_control(before, 4, dump(f), "json_patch")

    def test_envelope_validation(self):
        for mode in ("snapshot", "json_patch"):
            with self.assertRaises(Error):
                guarded_control({}, 0, "{}", mode)


if __name__ == "__main__":
    unittest.main()
