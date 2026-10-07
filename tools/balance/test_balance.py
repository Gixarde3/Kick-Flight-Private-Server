#!/usr/bin/env python3
"""Local acceptance test for the balance WebUI's master-override flow.

Uses only the standard library.  Copies ``config/masters_*.json`` into a temp *base* directory,
starts a mock ``/admin/maintenance`` endpoint plus a fake ``docker`` (so the API start-time and the
apply command can be exercised without Docker), then drives the WebUI HTTP API:

* reads come from the override file when present, else from the base file;
* saves write **only** to the override dir and never touch the base file;
* revert deletes the override (after a backup);
* export returns a zip of the override files;
* apply runs a configurable command and polls a health command;
* pending overrides are detected against the API container start time;
* effect-row add/delete and the core-table validation still work;
* maintenance is proxied to the mock admin endpoint;
* basic auth is enforced.

    python3 tools/balance/test_balance.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = Path("/tmp/kf-balance-test")
BASE = ROOT / "base"
OVERRIDES = ROOT / "overrides"
BACKUPS = ROOT / "backups"
FAKEBIN = ROOT / "fakebin"
STARTED_AT = ROOT / "started-at"
APPLIED_MARKER = ROOT / "applied.marker"
PORT = 18765
ADMIN_PORT = 19080
USER = "balance"
PASSWORD = "s3cret"

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, name, (": " + detail) if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


class MockAdmin(BaseHTTPRequestHandler):
    state = {"mode": "off", "title": "", "message": "", "noticeId": 0,
             "changedAtUtc": "2026-10-05T00:00:00Z"}

    def log_message(self, *args):
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/admin/maintenance":
            self.send_json(404, {})
            return
        self.send_json(200, dict(MockAdmin.state))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        MockAdmin.state["mode"] = payload.get("mode", "off")
        MockAdmin.state["title"] = payload.get("title", "")
        MockAdmin.state["message"] = payload.get("message", "")
        MockAdmin.state["noticeId"] += 1
        self.send_json(200, dict(MockAdmin.state))


def request(path, method="GET", body=None, auth=True, raw=False, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data, method=method)
    if method in ("POST", "PUT", "DELETE") or data is not None:
        # The WebUI now requires application/json on every state-changing request; callers pass a
        # headers override (e.g. Content-Type text/plain, a foreign Host) to test the rejections.
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    if auth:
        token = base64.b64encode(("%s:%s" % (USER, PASSWORD)).encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = response.read()
            if raw:
                return response.status, payload, dict(response.headers)
            text = payload.decode()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        payload = error.read()
        if raw:
            return error.code, payload, dict(error.headers)
        try:
            return error.code, (json.loads(payload.decode()) if payload else None)
        except ValueError:
            return error.code, payload.decode()


def build_fake_docker():
    FAKEBIN.mkdir(parents=True, exist_ok=True)
    script = FAKEBIN / "docker"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"inspect\" ]; then\n"
        "  cat \"$KF_FAKE_STARTED_AT\" 2>/dev/null || printf '%s\\n' '2000-01-01T00:00:00Z'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def started_at(value):
    STARTED_AT.write_text(value + "\n", encoding="utf-8")


def override_file(name):
    return OVERRIDES / ("masters_%s.json" % name)


def base_file(name):
    return BASE / ("masters_%s.json" % name)


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    BASE.mkdir(parents=True)
    OVERRIDES.mkdir(parents=True)
    BACKUPS.mkdir(parents=True)
    for path in (REPO / "config").glob("masters_*.json"):
        shutil.copy2(path, BASE / path.name)
    build_fake_docker()
    started_at("2099-01-01T00:00:00Z")   # nothing pending until a test says otherwise
    APPLIED_MARKER.unlink(missing_ok=True)

    admin = ThreadingHTTPServer(("127.0.0.1", ADMIN_PORT), MockAdmin)
    admin.daemon_threads = True
    threading.Thread(target=admin.serve_forever, daemon=True).start()

    env = dict(os.environ)
    env.update({
        "KF_BALANCE_BASE_DIR": str(BASE),
        "KF_BALANCE_OVERRIDE_DIR": str(OVERRIDES),
        "KF_BALANCE_BACKUP_DIR": str(BACKUPS),
        "KF_BALANCE_ADMIN_URL": "http://127.0.0.1:%d/admin/maintenance" % ADMIN_PORT,
        "KF_BALANCE_USER": USER,
        "KF_BALANCE_PASSWORD": PASSWORD,
        "KF_BALANCE_ALLOWED_HOSTS": "balance.test",
        "KF_BALANCE_API_CONTAINER": "fake-api",
        # A real restart changes the container start time; the fake one moves it forward too.
        "KF_BALANCE_APPLY_CMD": "printf applied > %s && printf '2099-06-01T00:00:00Z\\n' > %s"
                                % (APPLIED_MARKER, STARTED_AT),
        "KF_BALANCE_HEALTH_CMD": "true",
        "KF_BALANCE_APPLY_TIMEOUT": "3",
        "KF_BALANCE_HEALTH_INTERVAL": "0.2",
        "KF_FAKE_STARTED_AT": str(STARTED_AT),
        "PATH": str(FAKEBIN) + os.pathsep + env.get("PATH", ""),
    })
    webui = subprocess.Popen(
        [sys.executable, str(REPO / "tools/balance/server.py"),
         "--host", "127.0.0.1", "--port", str(PORT)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        wait_for_port(webui)

        # -- auth -----------------------------------------------------------------
        status, _ = request("/api/discs", auth=False)
        check("GET without credentials is 401", status == 401, "got %s" % status)
        status, discs = request("/api/discs")
        check("GET with credentials is 200 + disc list",
              status == 200 and isinstance(discs, list) and discs, "status %s" % status)

        # -- CSRF / DNS-rebinding protection --------------------------------------
        status, _ = request("/api/discs", headers={"Host": "evil.example"})
        check("foreign Host -> 403", status == 403, "got %s" % status)
        status, _ = request("/api/discs", headers={"Origin": "http://evil.example"})
        check("foreign Origin -> 403", status == 403, "got %s" % status)
        status, _ = request("/api/maintenance", "POST", {"mode": "off"},
                            headers={"Content-Type": "text/plain"})
        check("text/plain POST -> 415", status == 415, "got %s" % status)
        status, _ = request("/api/discs")
        check("legit request -> 200", status == 200, "got %s" % status)
        status, _ = request("/api/discs", headers={"Host": "balance.test"})
        check("extra KF_BALANCE_ALLOWED_HOSTS host -> 200", status == 200, "got %s" % status)
        status, _ = request("/api/discs", headers={"Origin": "http://127.0.0.1:%d" % PORT})
        check("same-origin Origin -> 200", status == 200, "got %s" % status)

        # -- override read: no override yet -> base file --------------------------
        status, tables = request("/api/tables")
        by_name = {t["name"]: t for t in (tables or [])}
        check("GET /api/tables lists the base tables",
              status == 200 and "skill_condition" in by_name and by_name["skill_condition"]["source"] == "base")
        check("nothing is overridden at the start",
              all(not t["overridden"] for t in by_name.values()))
        base_bytes = base_file("skill_condition").read_bytes()
        status, rows = request("/api/table/skill_condition")
        check("read falls back to the base file",
              status == 200 and rows == json.loads(base_bytes.decode()), "status %s" % status)

        # -- write: goes to the override dir, base file untouched -----------------
        disc = next(d for d in discs if d.get("skillId"))
        skill_id = disc["skillId"]
        status, schema = request("/api/effect-schema")
        spec = schema["tables"]["skill_condition"]
        new_id = (max(r["id"] for r in rows) + 1) if rows else 1
        new_row = {"id": new_id, "skillId": skill_id}
        new_row.update(spec["defaults"])
        status, result = request("/api/table/skill_condition", "POST", {"rows": rows + [new_row]})
        check("POST writes the override", status == 200 and result and result.get("ok") is True,
              "status %s body %s" % (status, result))
        check("override file exists", override_file("skill_condition").is_file())
        check("base file was not modified", base_file("skill_condition").read_bytes() == base_bytes)
        on_disk = json.loads(override_file("skill_condition").read_text())
        check("new row is in the override file",
              any(r["id"] == new_id and r["skillId"] == skill_id for r in on_disk))
        check("backup of the previous state was written", any(BACKUPS.iterdir()))

        # -- override read: now the override wins --------------------------------
        status, tables = request("/api/tables")
        by_name = {t["name"]: t for t in (tables or [])}
        check("table is reported as overridden", by_name["skill_condition"]["overridden"] is True)
        status, rows2 = request("/api/table/skill_condition")
        check("read returns the override row", any(r["id"] == new_id for r in rows2))

        # -- pending detection against the container start time -------------------
        started_at("2000-01-01T00:00:00Z")   # older than the override -> pending
        status, apply_state = request("/api/apply")
        check("override newer than the API start is pending",
              status == 200 and "skill_condition" in (apply_state.get("pending") or []),
              "status %s %s" % (status, apply_state))
        started_at("2099-01-01T00:00:00Z")   # newer than the override -> not pending
        status, apply_state = request("/api/apply")
        check("override older than the API start is not pending",
              status == 200 and "skill_condition" not in (apply_state.get("pending") or []),
              "status %s %s" % (status, apply_state))

        # -- export zip -----------------------------------------------------------
        status, payload, headers = request("/api/overrides/export", raw=True)
        names = []
        if status == 200:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = archive.namelist()
        check("export returns a zip with the override file",
              status == 200 and "masters_skill_condition.json" in names,
              "status %s names %s" % (status, names))
        check("export has an attachment filename",
              "attachment" in headers.get("Content-Disposition", ""))

        # -- revert ---------------------------------------------------------------
        base_before_revert = base_file("skill_condition").read_bytes()
        status, result = request("/api/table/skill_condition/revert", "POST")
        check("revert succeeds", status == 200 and result and result.get("ok") is True,
              "status %s body %s" % (status, result))
        check("override file is gone", not override_file("skill_condition").exists())
        check("base file is still untouched after revert",
              base_file("skill_condition").read_bytes() == base_before_revert)
        status, rows3 = request("/api/table/skill_condition")
        check("read falls back to base after revert", rows3 == json.loads(base_before_revert.decode()))
        status, tables = request("/api/tables")
        by_name = {t["name"]: t for t in (tables or [])}
        check("table is no longer overridden", by_name["skill_condition"]["overridden"] is False)
        status, result = request("/api/table/skill_condition/revert", "POST")
        check("reverting a non-overridden table is 404", status == 404, "status %s" % status)

        # -- effect add/delete still works on the override flow -------------------
        status, table = request("/api/table/skill_condition")
        next_id = (max(r["id"] for r in table) + 1) if table else 1
        added = {"id": next_id, "skillId": skill_id}
        added.update(spec["defaults"])
        status, result = request("/api/table/skill_condition", "POST", {"rows": table + [added]})
        check("add an effect row through the override flow",
              status == 200 and result and result.get("ok") is True, "status %s" % status)
        status, table2 = request("/api/table/skill_condition")
        status, result = request("/api/table/skill_condition", "POST",
                                 {"rows": [r for r in table2 if r["id"] != next_id]})
        check("delete the effect row through the override flow",
              status == 200 and result and result.get("ok") is True, "status %s" % status)

        # -- validation -----------------------------------------------------------
        bad_type = dict(spec["defaults"])
        bad_type.update({"id": 999999, "skillId": skill_id})
        bad_type["conditionType"] = "not-a-number"
        status, result = request("/api/table/skill_condition", "POST", {"rows": table + [bad_type]})
        check("wrong type is rejected with 400", status == 400, "status %s" % status)
        status, core = request("/api/table/disc")
        status2, _ = request("/api/table/disc", "POST", {"rows": core + [dict(core[0], id=99999999)]})
        check("core table still refuses add/delete", status2 == 400, "status %s" % status2)

        # -- apply ----------------------------------------------------------------
        APPLIED_MARKER.unlink(missing_ok=True)
        status, applied = request("/api/apply", "POST")
        check("POST /api/apply runs the command and reports health",
              status == 200 and applied and applied.get("ok") is True and
              applied["health"]["ok"] is True, "status %s body %s" % (status, applied))
        check("apply command was executed", APPLIED_MARKER.is_file())

        # -- maintenance ----------------------------------------------------------
        status, state = request("/api/maintenance")
        check("GET /api/maintenance proxies the admin endpoint",
              status == 200 and state.get("mode") == "off", "status %s %s" % (status, state))
        status, state = request("/api/maintenance", "POST",
                                {"mode": "warning", "title": "T", "message": "M"})
        check("POST warning reaches the admin endpoint",
              status == 200 and state.get("mode") == "warning" and state.get("message") == "M",
              "status %s %s" % (status, state))
        status, state = request("/api/maintenance", "POST", {"mode": "hard"})
        check("POST hard reaches the admin endpoint",
              status == 200 and state.get("mode") == "hard", "status %s %s" % (status, state))
        status, _ = request("/api/maintenance", "POST", {"mode": "bogus"})
        check("invalid maintenance mode is rejected", status == 400, "status %s" % status)

        # -- apply failure is reported, not swallowed -----------------------------
        check("failing apply command returns an error", _failing_apply_works(env, "exit 3"))
        check("apply that exits 0 without restarting is an error", _failing_apply_works(env, "true"))
    finally:
        webui.terminate()
        try:
            webui.wait(timeout=5)
        except subprocess.TimeoutExpired:
            webui.kill()
        admin.shutdown()

    print()
    if FAILURES:
        print("FAILED (%d): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL TESTS PASSED")
    return 0


def wait_for_port(webui):
    deadline = time.time() + 15
    while time.time() < deadline:
        if webui.poll() is not None:
            break
        try:
            request("/favicon.ico")
            print("WebUI is up on port %d" % PORT)
            return
        except Exception:
            time.sleep(0.2)
    output = webui.stdout.read().decode("utf-8", "replace") if webui.stdout else ""
    print("WebUI did not start:\n" + output)
    raise SystemExit(1)


def _failing_apply_works(base_env, command):
    env = dict(base_env)
    env["KF_BALANCE_APPLY_CMD"] = command
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "tools/balance/server.py"), "--host", "127.0.0.1",
         "--port", str(PORT + 1)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(80):
            try:
                req = urllib.request.Request("http://127.0.0.1:%d/api/apply" % (PORT + 1), method="POST")
                req.add_header("Content-Type", "application/json")
                token = base64.b64encode(("%s:%s" % (USER, PASSWORD)).encode()).decode()
                req.add_header("Authorization", "Basic " + token)
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status == 502 or False
            except urllib.error.HTTPError as error:
                if error.code == 502:
                    return True
                return False
            except urllib.error.URLError:
                time.sleep(0.1)
        return False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
