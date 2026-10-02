import importlib.util
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch-il2cpp-endpoints.py"
SPEC = importlib.util.spec_from_file_location("patch_il2cpp_endpoints", PATCHER)
PATCHER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER_MODULE)


def branch_target(pc, instruction):
    imm = instruction & 0x03FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    return pc + imm * 4


class AssetBundleUnloadCleanupPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patches = PATCHER_MODULE.NATIVE_PATCHES["arm64-v8a"]
        cls.hook = next(p for p in patches if p["offset"] == 0x1A830B8)
        cls.cave = next(p for p in patches if p["offset"] == 0x13CE6D8)
        cls.code = cls.cave["replacement"]

    def test_entry_branch_and_cave_calls_preserve_the_callback_return_path(self):
        self.assertEqual(self.hook["expected"], bytes.fromhex("f50f1df8"))
        hook_instruction = struct.unpack("<I", self.hook["replacement"])[0]
        self.assertEqual(hook_instruction >> 26, 0b000101, "function entry must branch without replacing LR")
        self.assertEqual(branch_target(self.hook["offset"], hook_instruction), self.cave["offset"])

        self.assertEqual(len(self.cave["expected"]), len(self.code))
        words = [struct.unpack_from("<I", self.code, i)[0] for i in range(0, len(self.code), 4)]
        self.assertEqual(words[3], 0xA9037BFD, "cave saves caller x29/x30 before calls")
        self.assertEqual(words[-2], 0xA8C453F3, "cave restores saved x19/x20")
        self.assertEqual(words[-1], 0xD65F03C0, "cave returns through the saved caller LR")

        call_targets = set()
        for i, word in enumerate(words):
            if word >> 26 == 0b100101:
                call_targets.add(branch_target(self.cave["offset"] + i * 4, word))
        self.assertEqual(
            call_targets,
            {0x2920B7C, 0x291DB50, 0x291DCD8, 0x1D7E9B4, 0x1A82CC8},
            "cave calls the singleton, pool accessors, string comparison, and ResourceManager removal",
        )

    def test_filter_removes_only_active_unloading_records_and_handles_duplicate_names(self):
        # Contract vector for the machine-code filter: duplicate ES infos all drain, while a newly
        # loaded/reused record with the same logical name and unrelated bundles survive.
        rows = [
            {"name": "font/localize/es/font.unity3d", "active": True, "state": 3}
            for _ in range(4)
        ] + [
            {"name": "font/localize/es/font.unity3d", "active": True, "state": 1},
            {"name": "font/localize/en/font.unity3d", "active": True, "state": 3},
            {"name": "font/localize/es/font.unity3d", "active": False, "state": 3},
        ]
        selected = [
            row for row in rows
            if row["active"] and row["state"] == 3 and row["name"] == "font/localize/es/font.unity3d"
        ]
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(row["state"] == 3 for row in selected))
        self.assertNotIn(rows[4], selected, "a same-name loaded/reused record must remain")
        self.assertNotIn(rows[5], selected, "a different bundle name must remain")
        self.assertNotIn(rows[6], selected, "an inactive pool slot must remain untouched")

        # The cave must implement the same three predicates and walk backward so removals cannot
        # shift unvisited lower pool indexes.
        required_words = {
            0x394092E8,  # ldrb w8, [x23, #0x24] (IsActive)
            0xB94022E8,  # ldr w8, [x23, #0x20] (State)
            0x71000D1F,  # cmp w8, #3 (Unloading)
            0xF9400AE1,  # ldr x1, [x23, #0x10] (Name)
            0x710006D6,  # subs w22, w22, #1 (reverse index iteration)
        }
        self.assertTrue(required_words.issubset(set(struct.unpack_from("<I", self.code, i)[0] for i in range(0, len(self.code), 4))))


if __name__ == "__main__":
    unittest.main()
