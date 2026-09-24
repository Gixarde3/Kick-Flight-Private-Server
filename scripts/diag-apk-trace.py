#!/usr/bin/env python3
"""Build and inspect a trace-only Kick-Flight APK profile.

The build profile reuses the repository's guarded production patches and the
existing KFDIAG/KF_NRE_LR probes. Capture is read-only on the device; analysis
works entirely on saved logcat/tombstone files.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts" / "patch-il2cpp-endpoints.py"
BUILDER = ROOT / "scripts" / "build-direct-apk.sh"
PROFILE_SWITCHES = (
    "KF_DIAG", "KF_NRE_LR", "KF_UNLOAD_BYPASS", "KF_FORCE_GAME_SCENE",
    "KF_UNITY_NO_ALLOCATOR_REBIND", "KF_PHOTON", "KF_NO_READY_SCENE",
    "KF_RESULT_DIAG", "KF_PHOTON_HOST",
)
PHOTON_HOST_DEFAULT = "51.79.241.70"


def profile_environment(flow: str = "photon", photon_host: str = PHOTON_HOST_DEFAULT, diagnostics: bool = True) -> dict[str, str | None]:
    environment: dict[str, str | None] = {
        "KF_DIAG": "1" if diagnostics else None,
        "KF_NRE_LR": "1" if diagnostics else None,
    # The wrapper deliberately clears behavior-changing experiments. These
    # values are recorded in the build manifest for comparison between runs.
        "KF_UNLOAD_BYPASS": None,
        "KF_FORCE_GAME_SCENE": None,
        "KF_UNITY_NO_ALLOCATOR_REBIND": None,
        "KF_PHOTON": "1" if flow == "photon" else None,
        "KF_NO_READY_SCENE": None,
        "KF_RESULT_DIAG": None,
        "KF_PHOTON_HOST": photon_host if flow == "photon" else None,
    }
    return environment
APK_ENTRIES = {
    "arm64": "lib/arm64-v8a/libil2cpp.so",
    "armv7": "lib/armeabi-v7a/libil2cpp.so",
    "unity": "lib/arm64-v8a/libunity.so",
    "metadata": "assets/bin/Data/Managed/Metadata/global-metadata.dat",
}
SCUDO_RE = re.compile(r"Scudo (?:ERROR: )?(?:corrupted chunk header|reportHeaderCorruption)", re.I)
FRAME_RE = re.compile(r"(?:^|[\s:])#(?P<index>\d+)\s+pc\s+(?P<pc>[0-9a-fA-F]+)\s+(?P<tail>.*)$")
LOGCAT_TIME_RE = re.compile(
    r"^(?P<stamp>(?:\d{4}-)?\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,6})"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_patcher_for_profile(environment: dict[str, str | None]) -> Any:
    old_values = {key: os.environ.get(key) for key in PROFILE_SWITCHES}
    try:
        for key in PROFILE_SWITCHES:
            value = environment.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        spec = importlib.util.spec_from_file_location("kf_trace_patcher", PATCHER)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load patcher: {PATCHER}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def profile_report(
    source_apk: Path,
    base_url: str,
    flow: str = "photon",
    photon_host: str = PHOTON_HOST_DEFAULT,
    diagnostics: bool = True,
    keep_native_bytes: bool = False,
) -> dict[str, Any]:
    """Apply the real patch functions to temporary APK members and return diffs."""
    source_apk = source_apk.resolve()
    if not source_apk.is_file():
        raise FileNotFoundError(f"source APK not found: {source_apk}")
    environment = profile_environment(flow, photon_host, diagnostics)
    patcher = load_patcher_for_profile(environment)
    normalized_url, authority = patcher.normalize_base_url(base_url)
    source_hashes: dict[str, str] = {}
    reports: dict[str, list[dict[str, Any]]] = {"metadata": [], "native": []}
    patched_native: dict[str, bytes] = {}
    source_manifest_sha256 = ""

    with zipfile.ZipFile(source_apk) as apk, tempfile.TemporaryDirectory(prefix="kf-diag-plan-") as tmp_name:
        try:
            source_manifest_sha256 = sha256_bytes(apk.read("AndroidManifest.xml"))
        except KeyError as exc:
            raise ValueError(f"{source_apk} is missing AndroidManifest.xml") from exc
        tmp = Path(tmp_name)
        files: dict[str, Path] = {}
        for key, member in APK_ENTRIES.items():
            try:
                payload = apk.read(member)
            except KeyError as exc:
                raise ValueError(f"{source_apk} is missing APK member {member}") from exc
            source_hashes[key] = sha256_bytes(payload)
            target = tmp / key / Path(member).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            files[key] = target

        reports["metadata"] = patcher.patch_metadata(
            files["metadata"], normalized_url, authority,
            environment.get("KF_PHOTON_HOST"),
        )
        reports["native"].extend(patcher.patch_native(files["arm64"], "arm64-v8a"))
        reports["native"].extend(patcher.patch_native(files["armv7"], "armeabi-v7a"))
        reports["native"].extend(patcher.patch_unity_native(files["unity"], "arm64-v8a"))
        if keep_native_bytes:
            patched_native = {key: files[key].read_bytes() for key in ("arm64", "armv7", "unity")}

    result = {
        "sourceApk": str(source_apk),
        "sourceApkSha256": sha256_file(source_apk),
        "sourceManifestSha256": source_manifest_sha256,
        "builderManifestTransform": {
            "android:debuggable": "true",
            "android:allowNativeHeapPointerTagging": "false",
            "android:largeHeap": "true",
            "description": "same manifest transformation as the baseline build in scripts/build-direct-apk.sh",
        },
        "sourceEntrySha256": source_hashes,
        "baseUrl": normalized_url,
        "profile": environment,
        "patcherSha256": sha256_file(PATCHER),
        "builderSha256": sha256_file(BUILDER),
        "patchReport": reports,
        "patchCounts": {
            "metadataLiterals": len(reports["metadata"]),
            "native": len(reports["native"]),
            "libunity": sum(1 for item in reports["native"] if item.get("library") == "libunity.so"),
            "KFDIAGProbeEntries": sum(
                1 for item in reports["native"]
                if "DIAG" in str(item.get("description", ""))
            ),
        },
        "notes": [
            "libunity allocator rebind is enabled because KF_UNITY_NO_ALLOCATOR_REBIND is unset.",
            "KFDIAG observes IL2CPP state; it does not identify the original writer of a corrupted heap header.",
        ],
    }
    if keep_native_bytes:
        result["_patchedNative"] = patched_native
    return result


def patch_delta(baseline: dict[str, Any], traced: dict[str, Any]) -> dict[str, Any]:
    def slot_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (str(item.get("abi", "")), str(item.get("library", "libil2cpp.so")), str(item.get("offset", "")))

    def slots(report: dict[str, Any], data: dict[str, bytes]) -> dict[tuple[str, str, str], dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for item in report["patchReport"]["native"]:
            grouped.setdefault(slot_key(item), []).append(item)
        result: dict[tuple[str, str, str], dict[str, Any]] = {}
        for key, entries in grouped.items():
            abi, library, offset_text = key
            member = "unity" if library == "libunity.so" else ("armv7" if abi == "armeabi-v7a" else "arm64")
            offset = int(offset_text, 16)
            length = max(len(bytes.fromhex(str(entry["to"]))) for entry in entries)
            result[key] = {
                "abi": abi,
                "library": library,
                "offset": offset_text,
                "bytes": data[member][offset:offset + length].hex(),
                "description": entries[-1].get("description", ""),
            }
        return result

    baseline_data = baseline["_patchedNative"]
    trace_data = traced["_patchedNative"]
    baseline_slots = slots(baseline, baseline_data)
    trace_slots = slots(traced, trace_data)
    added = [trace_slots[key] for key in sorted(trace_slots.keys() - baseline_slots.keys())]
    removed = [baseline_slots[key] for key in sorted(baseline_slots.keys() - trace_slots.keys())]
    changed = [
        {"baseline": baseline_slots[key], "trace": trace_slots[key]}
        for key in sorted(baseline_slots.keys() & trace_slots.keys())
        if baseline_slots[key]["bytes"] != trace_slots[key]["bytes"]
    ]

    binary_byte_ranges: list[dict[str, Any]] = []
    for member in ("arm64", "armv7", "unity"):
        before, after = baseline_data[member], trace_data[member]
        start: int | None = None
        before_run = bytearray()
        after_run = bytearray()
        for offset, (old, new) in enumerate(zip(before, after)):
            if old != new:
                if start is None:
                    start = offset
                before_run.append(old)
                after_run.append(new)
            elif start is not None:
                binary_byte_ranges.append({"member": member, "offset": f"0x{start:x}", "from": before_run.hex(), "to": after_run.hex()})
                start, before_run, after_run = None, bytearray(), bytearray()
        if start is not None:
            binary_byte_ranges.append({"member": member, "offset": f"0x{start:x}", "from": before_run.hex(), "to": after_run.hex()})

    return {
        "baselineFlow": baseline["profile"].get("KF_PHOTON"),
        "traceFlow": traced["profile"].get("KF_PHOTON"),
        "baselinePhotonHost": baseline["profile"].get("KF_PHOTON_HOST"),
        "tracePhotonHost": traced["profile"].get("KF_PHOTON_HOST"),
        "added": added,
        "removed": removed,
        "changed": changed,
        "binaryByteRanges": binary_byte_ranges,
        "counts": {
            "addedSlots": len(added),
            "removedSlots": len(removed),
            "changedSlots": len(changed),
            "binaryByteRanges": len(binary_byte_ranges),
        },
    }


def dump_json(value: Any, path: Path | None = None) -> None:
    serialized = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(serialized, end="")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(serialized, encoding="utf-8")
        temp.replace(path)


def parse_builder_patch_report(output: str) -> dict[str, Any] | None:
    marker = re.search(r"(?m)^\{\n\s+\"baseUrl\":", output)
    if not marker:
        return None
    try:
        parsed, _ = json.JSONDecoder().raw_decode(output[marker.start():])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build(args: argparse.Namespace) -> int:
    source_apk = args.source_apk.resolve()
    output_apk = args.output.resolve()
    if source_apk == output_apk:
        raise ValueError("output APK must differ from the source APK")

    plan = profile_report(
        source_apk, args.base_url, args.flow, args.photon_host,
        diagnostics=True, keep_native_bytes=args.compare_baseline,
    )
    if args.compare_baseline:
        baseline = profile_report(
            source_apk, args.base_url, args.flow, args.photon_host,
            diagnostics=False, keep_native_bytes=True,
        )
        plan["baselinePatchReport"] = baseline["patchReport"]
        plan["tracePatchDelta"] = patch_delta(baseline, plan)
        del baseline["_patchedNative"]
        del plan["_patchedNative"]
    if args.dry_run:
        dump_json(plan)
        return 0

    output_apk.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    build_environment = profile_environment(args.flow, args.photon_host, diagnostics=True)
    for key, value in build_environment.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    env["SOURCE_APK"] = str(source_apk)
    env["OUTPUT_APK"] = str(output_apk)
    env["SERVER_BASE_URL"] = args.base_url

    result = subprocess.run(
        ["bash", str(BUILDER)], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        print(f"Build failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode
    if not output_apk.is_file():
        raise RuntimeError(f"builder reported success but APK is missing: {output_apk}")

    with zipfile.ZipFile(output_apk) as built_apk:
        output_manifest_sha256 = sha256_bytes(built_apk.read("AndroidManifest.xml"))
    actual = parse_builder_patch_report(result.stdout)
    expected = plan["patchReport"]
    actual_patches = {"metadata": actual.get("metadata"), "native": actual.get("native")} if actual else None
    matches = actual_patches == expected and actual.get("photonHost") == (args.photon_host if args.flow == "photon" else None)
    manifest = {
        "format": "kickflight-diag-apk-manifest-v1",
        "builtAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "outputApk": str(output_apk),
        "outputApkSha256": sha256_file(output_apk),
        "manifest": {
            "sourceSha256": plan["sourceManifestSha256"],
            "outputSha256": output_manifest_sha256,
            "transform": plan["builderManifestTransform"],
        },
        "patchReportMatchesDryRun": matches,
        "patchReport": actual,
        "dryRun": plan,
        "signing": {
            "tool": "apksigner",
            "keystore": ".local/kickflight-test-signing.jks",
            "alias": "kickflight-test",
        },
    }
    manifest_path = args.manifest or Path(str(output_apk) + ".manifest.json")
    dump_json(manifest, manifest_path.resolve())
    print(f"Trace manifest: {manifest_path.resolve()}")
    if not matches:
        print("Build patch report differs from the APK dry-run; inspect the manifest before using this artifact.", file=sys.stderr)
        return 1
    return 0


def run_adb(serial: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", "-s", serial, *args], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def capture(args: argparse.Namespace) -> int:
    if shutil.which("adb") is None:
        raise RuntimeError("adb was not found in PATH")
    state = run_adb(args.serial, "get-state")
    if state.returncode != 0 or state.stdout.strip() != "device":
        raise RuntimeError(f"ADB target {args.serial!r} is not ready: {state.stderr.strip() or state.stdout.strip()}")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir.resolve() if args.output_dir else ROOT / ".local" / "diag-runs" / f"{stamp}-{args.serial}"
    output_dir.mkdir(parents=True, exist_ok=False)
    errors: list[str] = []
    commands: list[dict[str, Any]] = []

    logcat_cmd = ("logcat", "-d", "-v", "threadtime", "-b", "main,system,crash")
    logcat = run_adb(args.serial, *logcat_cmd)
    commands.append({"command": ["adb", "-s", args.serial, *logcat_cmd], "exitCode": logcat.returncode})
    (output_dir / "logcat-threadtime.txt").write_text(logcat.stdout, encoding="utf-8")
    if logcat.returncode:
        errors.append(f"logcat failed: {logcat.stderr.strip()}")

    crash_cmd = ("logcat", "-d", "-v", "threadtime", "-b", "crash")
    crash = run_adb(args.serial, *crash_cmd)
    commands.append({"command": ["adb", "-s", args.serial, *crash_cmd], "exitCode": crash.returncode})
    (output_dir / "logcat-crash-buffer.txt").write_text(crash.stdout, encoding="utf-8")
    if crash.returncode:
        errors.append(f"crash buffer capture failed: {crash.stderr.strip()}")

    tombstones: list[str] = []
    listing = run_adb(args.serial, "shell", "ls", "-1t", "/data/tombstones")
    commands.append({"command": ["adb", "-s", args.serial, "shell", "ls", "-1t", "/data/tombstones"], "exitCode": listing.returncode})
    candidates = [line.strip() for line in listing.stdout.splitlines() if re.fullmatch(r"tombstone_[0-9]+", line.strip())]
    if candidates:
        name = candidates[0]
        tombstone_cmd = ("exec-out", "cat", f"/data/tombstones/{name}")
        tombstone = run_adb(args.serial, *tombstone_cmd)
        commands.append({"command": ["adb", "-s", args.serial, *tombstone_cmd], "exitCode": tombstone.returncode})
        if tombstone.returncode == 0 and tombstone.stdout:
            tombstone_path = output_dir / name
            tombstone_path.write_text(tombstone.stdout, encoding="utf-8")
            tombstones.append(str(tombstone_path))
        else:
            errors.append(f"could not read {name}; device permissions may hide tombstones: {tombstone.stderr.strip()}")
    else:
        errors.append("no readable /data/tombstones entries were listed; logcat crash buffer was still captured")

    manifest = {
        "format": "kickflight-diag-capture-v1",
        "capturedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "serial": args.serial,
        "readOnly": True,
        "commands": commands,
        "errors": errors,
        "files": {},
    }
    for path in [output_dir / "logcat-threadtime.txt", output_dir / "logcat-crash-buffer.txt", *(Path(item) for item in tombstones)]:
        if path.exists():
            manifest["files"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    dump_json(manifest, output_dir / "capture.json")
    report = analyze_files([output_dir / "logcat-threadtime.txt", output_dir / "logcat-crash-buffer.txt", *(Path(item) for item in tombstones)])
    dump_json(report, output_dir / "analysis.json")
    print(f"Captured diagnostics in {output_dir}")
    for error in errors:
        print(f"Capture note: {error}", file=sys.stderr)
    print_analysis_summary(report)
    return 0 if logcat.returncode == 0 else 1


def parse_timestamp(line: str) -> dt.datetime | None:
    match = LOGCAT_TIME_RE.match(line)
    if not match:
        return None
    stamp = match.group("stamp")
    if not re.match(r"\d{4}-", stamp):
        stamp = f"2000-{stamp}"
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    try:
        parsed = dt.datetime.strptime(stamp, fmt)
    except ValueError:
        return None
    return parsed


def native_frame(line: str) -> dict[str, Any] | None:
    match = FRAME_RE.search(line)
    if not match:
        return None
    tail = match.group("tail").strip()
    module_match = re.search(r"(?:^|/)(?P<name>[^/\s]+\.so)(?:\s|$)", tail)
    pc_value = int(match.group("pc"), 16)
    return {
        "frame": int(match.group("index")),
        "pc": f"0x{pc_value:x}",
        "module": module_match.group("name") if module_match else None,
        "detail": tail,
    }


def analyze_files(paths: list[Path]) -> dict[str, Any]:
    input_info: list[dict[str, Any]] = []
    sources: list[tuple[str, list[str]]] = []
    seen_content: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"input file not found: {resolved}")
        raw = resolved.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        digest = sha256_bytes(raw)
        input_info.append({"path": str(resolved), "bytes": len(raw), "sha256": digest, "lineCount": len(lines)})
        if digest not in seen_content:
            sources.append((str(resolved), lines))
            seen_content.add(digest)

    kfdiag: list[dict[str, Any]] = []
    event_lines: list[dict[str, Any]] = []
    scudo_events: list[dict[str, Any]] = []
    scene_events: list[dict[str, Any]] = []
    seen_kfdiag: set[tuple[str | None, int, str]] = set()
    seen_event_lines: set[tuple[str | None, str]] = set()
    seen_scudo: dict[str, dict[str, Any]] = {}
    fatal_re = re.compile(r"SIGABRT|signal 6|SIGSEGV|Fatal signal|fatal signal", re.I)
    relevant_re = re.compile(r"KFDIAG|Scudo|SIGABRT|SIGSEGV|Fatal signal|HomeScene|GameScene|MatchingScene|TitleScene", re.I)

    for source, lines in sources:
        for i, line in enumerate(lines):
            diag_match = re.search(r"KFDIAG[^\n]*?\bv\s*=\s*(-?\d+)\b", line)
            if diag_match:
                stamp = parse_timestamp(line)
                key = (stamp.isoformat() if stamp else None, int(diag_match.group(1)), line.strip())
                if key not in seen_kfdiag:
                    seen_kfdiag.add(key)
                    kfdiag.append({"source": source, "line": i + 1, "value": int(diag_match.group(1)), "text": line.strip()})
            if relevant_re.search(line):
                item = {"source": source, "line": i + 1, "text": line.strip()}
                stamp = parse_timestamp(line)
                key = (stamp.isoformat() if stamp else None, line.strip())
                if key not in seen_event_lines:
                    seen_event_lines.add(key)
                    event_lines.append(item)
                if re.search(r"HomeScene|GameScene|MatchingScene|TitleScene", line):
                    scene_key = (stamp.isoformat() if stamp else None, line.strip())
                    if scene_key not in {(x["timestamp"], x["text"]) for x in scene_events}:
                        scene_events.append({**item, "timestamp": stamp.isoformat() if stamp else None})
            if SCUDO_RE.search(line):
                end = min(len(lines), i + 100)
                frame_list = [frame for frame in (native_frame(x) for x in lines[i:end]) if frame]
                context = "\n".join(lines[max(0, i - 6):min(end, i + 24)])
                all_crash_text = "\n".join(lines[max(0, i - 6):min(end, i + 24)])
                ts = parse_timestamp(line)
                last_home = None
                if ts:
                    for scene in reversed(scene_events):
                        if scene["source"] != source:
                            continue
                        scene_dt = parse_timestamp(scene["text"])
                        if scene_dt and scene_dt <= ts and "HomeScene" in scene["text"]:
                            last_home = scene_dt
                            break
                thread_match = re.search(r"\bname:\s*([^\s,]+)", context)
                thread = thread_match.group(1) if thread_match else None
                event_key = ts.isoformat() if ts else f"{source}:{i + 1}"
                event = {
                    "source": source,
                    "line": i + 1,
                    "timestamp": ts.isoformat() if ts else None,
                    "thread": thread,
                    "signal": "SIGABRT" if fatal_re.search(all_crash_text) else None,
                    "homeToScudoSeconds": round((ts - last_home).total_seconds(), 3) if ts and last_home else None,
                    "frames": frame_list,
                    "alsoInSources": [],
                }
                previous = seen_scudo.get(event_key)
                if previous is None:
                    seen_scudo[event_key] = event
                    scudo_events.append(event)
                elif source != previous["source"] and source not in previous["alsoInSources"]:
                    previous["alsoInSources"].append(source)
                    if not previous["frames"] and frame_list:
                        previous["frames"] = frame_list
                    if not previous["thread"] and thread:
                        previous["thread"] = thread
                    if not previous["signal"] and event["signal"]:
                        previous["signal"] = event["signal"]
                elif source == previous["source"]:
                    # Two Scudo lines in the same file at the same millisecond
                    # are distinct observations; keep both.
                    event_key = f"{event_key}#{i + 1}"
                    seen_scudo[event_key] = event
                    scudo_events.append(event)

    signatures: dict[str, int] = {}
    for event in scudo_events:
        signature = ",".join(f"{frame['module']}+{frame['pc']}" for frame in event["frames"][:12])
        if signature:
            signatures[signature] = signatures.get(signature, 0) + 1
    recent = event_lines[-100:]
    return {
        "format": "kickflight-diag-analysis-v1",
        "inputs": input_info,
        "counts": {
            "KFDIAG": len(kfdiag),
            "scudoCorruption": len(scudo_events),
            "nativeFatalLines": sum(1 for entry in event_lines if fatal_re.search(entry["text"])),
        },
        "lastKFDIAG": kfdiag[-100:],
        "sceneEvents": scene_events[-100:],
        "scudoEvents": scudo_events,
        "scudoFrameSignatures": signatures,
        "recentRelevantLines": recent,
        "interpretation": (
            "A Scudo corrupted-chunk abort identifies allocator detection during a heap operation. "
            "The captured deallocate stack can show where corruption was detected; it does not by itself "
            "identify which earlier write or allocation caused it. KFDIAG values trace IL2CPP probes and "
            "may not overlap the Unity graphics thread's native allocation history."
        ),
    }


def print_analysis_summary(report: dict[str, Any]) -> None:
    counts = report["counts"]
    print(f"KFDIAG records: {counts['KFDIAG']}; Scudo corruptions: {counts['scudoCorruption']}")
    for event in report["scudoEvents"]:
        frames = ", ".join(f"#{item['frame']} {item['module']}+{item['pc']}" for item in event["frames"][:12])
        print(f"Scudo at {event['source']}:{event['line']} thread={event['thread'] or 'unknown'} signal={event['signal'] or 'unknown'}")
        if event["homeToScudoSeconds"] is not None:
            print(f"  HomeScene → Scudo: {event['homeToScudoSeconds']:.3f}s")
        if frames:
            print(f"  Native frames: {frames}")
    if not report["scudoEvents"]:
        print("No Scudo corrupted-header signature found in the supplied files.")


def analyze(args: argparse.Namespace) -> int:
    paths = [args.logcat, *args.tombstone]
    report = analyze_files(paths)
    dump_json(report, args.output.resolve() if args.output else None)
    if args.output:
        print_analysis_summary(report)
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build_parser = commands.add_parser("build", help="build a trace APK, or validate exact patch deltas with --dry-run")
    build_parser.add_argument("--source-apk", type=Path, default=ROOT / "base.apk")
    build_parser.add_argument("--base-url", required=True, help="private server URL; only http:// is supported by the existing patcher")
    build_parser.add_argument("--flow", choices=("photon", "offline"), default="photon", help="must match the reference APK/game run")
    build_parser.add_argument("--photon-host", default=PHOTON_HOST_DEFAULT, help="Photon NameServer host (default: current LuxonServer)")
    build_parser.add_argument("--output", type=Path, default=ROOT / ".local/artifacts/KickFlight-2.11.0-DIAG.apk")
    build_parser.add_argument("--manifest", type=Path)
    build_parser.add_argument("--compare-baseline", action="store_true", help="include same-flow production-vs-DIAG patch delta")
    build_parser.add_argument("--dry-run", action="store_true", help="validate all exact patch guards on temporary APK members; do not build")
    build_parser.set_defaults(func=build)

    capture_parser = commands.add_parser("capture", help="save current logcat buffers and try to read the newest native tombstone (read-only)")
    capture_parser.add_argument("--serial", required=True, help="ADB serial, for example emulator-5562")
    capture_parser.add_argument("--output-dir", type=Path, help="new, empty output directory; defaults to .local/diag-runs/<UTC>-<serial>")
    capture_parser.set_defaults(func=capture)

    analyze_parser = commands.add_parser("analyze", help="analyze already-saved logcat and tombstone files without ADB")
    analyze_parser.add_argument("--logcat", type=Path, required=True)
    analyze_parser.add_argument("--tombstone", type=Path, action="append", default=[])
    analyze_parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    analyze_parser.set_defaults(func=analyze)
    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
