import importlib.util
import os
import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch-il2cpp-endpoints.py"
_OLD_KF_DIAG = os.environ.get("KF_DIAG")
os.environ["KF_DIAG"] = "1"
SPEC = importlib.util.spec_from_file_location("patch_il2cpp_endpoints", PATCHER)
PATCHER_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER_MODULE)
if _OLD_KF_DIAG is None:
    os.environ.pop("KF_DIAG", None)
else:
    os.environ["KF_DIAG"] = _OLD_KF_DIAG


class DiagStateProbeBranchTests(unittest.TestCase):
    def test_state_probe_caves_branch_to_move_next_continuations(self):
        expected = {
            "HomeScene.PreBeginAsync.MoveNext": 0x1595CB4,
            "TitleScene.PreBeginAsync.MoveNext": 0x31C7070,
            "SceneManager._ChangeSceneAsync.MoveNext": 0x1CB303C,
        }
        patches = PATCHER_MODULE.DIAG_PATCHES_ARM64

        for method, continuation in expected.items():
            with self.subTest(method=method):
                patch = next(
                    patch
                    for patch in patches
                    if patch["description"].startswith(f"DIAG cave: {method}")
                )
                code = patch["replacement"]
                # Replaying this load preserves the original displaced instruction's result.
                self.assertEqual(code[-8:-4], bytes.fromhex("681240b9"))
                # The cave calls log helpers with BL, so ending in RET would return into the cave
                # through the overwritten LR instead of resuming the state machine.
                branch_site = int(patch["offset"]) + len(code) - 4
                instruction = struct.unpack("<I", code[-4:])[0]
                self.assertEqual(instruction >> 26, 0b000101, "final instruction must be B")
                displacement = instruction & 0x03FFFFFF
                if displacement & (1 << 25):
                    displacement -= 1 << 26
                self.assertEqual(branch_site + displacement * 4, continuation)

        hook = next(
            patch
            for patch in patches
            if patch["description"].startswith(
                "DIAG hook: SceneManager._ChangeSceneAsync.MoveNext"
            )
        )
        self.assertEqual(hook["offset"], 0x1CB3038)
        self.assertEqual(hook["expected"], bytes.fromhex("681240b9"))
        instruction = struct.unpack("<I", hook["replacement"])[0]
        self.assertEqual(instruction >> 26, 0b100101, "hook must BL the diagnostic cave")
        displacement = instruction & 0x03FFFFFF
        if displacement & (1 << 25):
            displacement -= 1 << 26
        self.assertEqual(0x1CB3038 + displacement * 4, 0x13CE69C)


if __name__ == "__main__":
    unittest.main()
