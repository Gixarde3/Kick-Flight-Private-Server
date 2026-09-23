#!/usr/bin/env python3
"""Raise the Octo Java downloader's HTTP timeouts in classes2.dex.

jp.qualiarts.octo.lib.HttpAsyncTask (the native downloader the Octo SDK uses on Android) hard-codes
setConnectTimeout(10000)/setReadTimeout(10000). Over a slow or busy link (remote play on mobile data through
the home uplink, ~10 parallel transfers) the 10 s read timeout fires on the bigger bundles, the SDK reports
"octo.network.timeout" and the DownloadScene shows "communication error" every 20-30 s. This bumps connect to
20 s and read to 120 s. Usage: patch-octo-http-timeout.py <decoded-apk-dir> (needs apktool + java).
"""
import shutil, subprocess, sys, zipfile
from pathlib import Path

APKTOOL = Path(__file__).resolve().parents[2] / "Kick-Flight-Assets/apk_patch_pipeline/.tools/apktool_3.0.3.jar"
CONNECT_MS, READ_MS = 20_000, 120_000


def main() -> int:
    decoded = Path(sys.argv[1]).resolve()
    dex = decoded / "classes2.dex"
    work = decoded.parent / "octo-dex"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    mini = work / "mini.apk"
    # apktool wants a real (binary) manifest even with --no-res; borrow the decoded APK's original one
    with zipfile.ZipFile(mini, "w") as z:
        z.write(dex, "classes.dex")
        z.write(decoded / "original/AndroidManifest.xml", "AndroidManifest.xml")
    subprocess.check_call(["java", "-jar", str(APKTOOL), "d", "-f", "--no-res", "-o", str(work / "d"), str(mini)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    smali = work / "d/smali/jp/qualiarts/octo/lib/HttpAsyncTask.smali"
    text = smali.read_text(encoding="utf-8")
    old = ("    const/16 v5, 0x2710\n\n"
           "    invoke-virtual {v3, v5}, Ljava/net/HttpURLConnection;->setConnectTimeout(I)V\n\n"
           "    invoke-virtual {v3, v5}, Ljava/net/HttpURLConnection;->setReadTimeout(I)V\n")
    new = (f"    const v5, {CONNECT_MS:#x}\n\n"
           "    invoke-virtual {v3, v5}, Ljava/net/HttpURLConnection;->setConnectTimeout(I)V\n\n"
           f"    const v5, {READ_MS:#x}\n\n"
           "    invoke-virtual {v3, v5}, Ljava/net/HttpURLConnection;->setReadTimeout(I)V\n")
    if old not in text:
        raise SystemExit("HttpAsyncTask.smali: timeout sequence not found (already patched or different build)")
    smali.write_text(text.replace(old, new), encoding="utf-8")
    subprocess.check_call(["java", "-jar", str(APKTOOL), "b", "-o", str(work / "out.apk"), str(work / "d")],
                          stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    with zipfile.ZipFile(work / "out.apk") as z:
        patched = z.read("classes.dex")
    dex.write_bytes(patched)
    print(f"classes2.dex: Octo HttpAsyncTask timeouts -> connect {CONNECT_MS} ms, read {READ_MS} ms ({len(patched)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
