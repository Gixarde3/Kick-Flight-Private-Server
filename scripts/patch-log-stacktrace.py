#!/usr/bin/env python3
"""patch-log-stacktrace.py <decoded-apk-dir>

Turn off Unity's stack-trace capture for Warning and Log messages (PlayerSettings.m_StackTraceTypes inside
assets/bin/Data/data.unity3d). Under the emulator's ARM translation layer the capture routine (libunity+0x344238,
~37 KB stack frame) intermittently SIGSEGVs on the UnityPreload thread while the GameScene / GameReadyScene assets
load and log their "referenced script is missing" warnings - a hang at the loading screen that predates every
gameplay patch (logs from 2026-09-12 on). Error/Assert/Exception keep their traces (NullReferenceException stacks
in logcat are how we debug). LogType order: Error, Assert, Warning, Log, Exception (+1 spare).
"""
import sys
from pathlib import Path

import UnityPy

NONE, SCRIPT_ONLY = 0, 1
QUIET = {2, 3}  # Warning, Log


def main() -> int:
    decoded = Path(sys.argv[1])
    path = decoded / "assets" / "bin" / "Data" / "data.unity3d"
    env = UnityPy.load(str(path))
    bundle = next(iter(env.files.values()))
    ggm = bundle.files["globalgamemanagers"]
    for obj in ggm.objects.values():
        if obj.type.name != "PlayerSettings":
            continue
        tree = obj.read_typetree()
        before = list(tree["m_StackTraceTypes"])
        tree["m_StackTraceTypes"] = [NONE if i in QUIET else v for i, v in enumerate(before)]
        obj.save_typetree(tree)
        data = bundle.save(packer="original")
        path.write_bytes(data)
        check = UnityPy.load(str(path))
        after = None
        for o in next(iter(check.files.values())).files["globalgamemanagers"].objects.values():
            if o.type.name == "PlayerSettings":
                after = o.read_typetree()["m_StackTraceTypes"]
        print(f"PlayerSettings.m_StackTraceTypes {before} -> {after} ({len(data)} bytes)")
        return 0
    raise SystemExit("PlayerSettings not found in globalgamemanagers")


if __name__ == "__main__":
    sys.exit(main())
