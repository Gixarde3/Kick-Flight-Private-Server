#!/usr/bin/env python3
"""Local balance WebUI for the Kick-Flight combat master tables.

Serves ``tools/balance/index.html``, the icon folder and a small JSON API over
``config/masters_*.json`` so the KS/SS/disc/kicker numbers can be tuned from the
browser.  Python standard library only; nothing here needs the game server.

    python tools/balance/server.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BALANCE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BALANCE_DIR.parent.parent
CONFIG_DIR = REPO_ROOT / "config"
DOCS_DIR = REPO_ROOT / "docs"
ICON_DIR = BALANCE_DIR / "icons"
BACKUP_DIR = BALANCE_DIR / "backups"
INDEX_FILE = BALANCE_DIR / "index.html"
DISC_CARDS_FILE = DOCS_DIR / "disc_cards.json"

TABLE_NAME_RE = re.compile(r"^[a-z_]+$")
ICON_NAME_RE = re.compile(r"^(?:kicker|disc)_[0-9]+\.png$")
TABLE_URL_RE = re.compile(r"^/api/table/([^/]*)$")
DIFF_URL_RE = re.compile(r"^/api/diff/([^/]*)$")

MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_REPORTED_ERRORS = 12
WRITE_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


def table_path(name):
    """config/masters_<name>.json for a well-formed name that exists, else None."""
    if not TABLE_NAME_RE.match(name):
        return None
    path = CONFIG_DIR / ("masters_%s.json" % name)
    return path if path.is_file() else None


def read_table(name):
    """Return the row list of config/masters_<name>.json."""
    path = table_path(name)
    if path is None:
        raise FileNotFoundError(name)
    with path.open(encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError("config/masters_%s.json is not a JSON array" % name)
    return rows


def load_disc_cards():
    """docs/disc_cards.json -> {disc id (str): card dict}.

    The file stores the cards as a list under the ``cards`` key; a mapping keyed
    directly by disc id is also accepted so the tool keeps working if the file is
    reshaped.
    """
    if not DISC_CARDS_FILE.is_file():
        return {}
    with DISC_CARDS_FILE.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    source = doc.get("cards") if isinstance(doc, dict) else doc
    cards = {}
    if isinstance(source, list):
        for card in source:
            if isinstance(card, dict) and "discId" in card:
                cards[str(card["discId"])] = card
    elif isinstance(source, dict):
        for key, card in source.items():
            if key.startswith("_") or not isinstance(card, dict):
                continue
            cards[str(card.get("discId", key))] = card
    return cards


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


def value_kind(value):
    """Classify a JSON value the way the writer needs to reproduce it."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "other"


def describe(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return "a string (%r)" % (value if len(value) <= 40 else value[:40] + "...")
    return "a %s" % value_kind(value)


def normalize_id(value):
    """Ids keep their type; 100.0 is accepted for an int id and stored as 100."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def coerce_value(kind, value, where):
    """(coerced value, None) or (None, error message) preserving the field type."""
    if kind == "bool":
        if isinstance(value, bool):
            return value, None
        return None, "%s: expected true/false, got %s" % (where, describe(value))
    if kind == "int":
        if isinstance(value, bool):
            return None, "%s: expected an integer, got %s" % (where, describe(value))
        if isinstance(value, int):
            return value, None
        if isinstance(value, float):
            if not math.isfinite(value):
                return None, "%s: expected a finite integer" % where
            if value.is_integer():
                return int(value), None
            return None, "%s: expected an integer, got %s" % (where, describe(value))
        return None, "%s: expected an integer, got %s" % (where, describe(value))
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "%s: expected a number, got %s" % (where, describe(value))
        number = float(value)
        if not math.isfinite(number):
            return None, "%s: expected a finite number" % where
        return number, None
    if kind == "str":
        if isinstance(value, str):
            return value, None
        return None, "%s: expected a string, got %s" % (where, describe(value))
    if kind == "null":
        if value is None:
            return value, None
        return None, "%s: expected null, got %s" % (where, describe(value))
    return None, "%s: unsupported field type %s" % (where, kind)


class Problems:
    """Collects validation errors without letting the list grow without bound."""

    def __init__(self):
        self.messages = []
        self.withheld = 0

    def add(self, message):
        if len(self.messages) < MAX_REPORTED_ERRORS:
            self.messages.append(message)
        else:
            self.withheld += 1

    def result(self):
        messages = list(self.messages)
        if self.withheld:
            messages.append("... and %d more problem(s)" % self.withheld)
        return messages


def validate_row(current, posted, table, problems):
    """Return the row to write, or None when it fails validation."""
    row_id = current.get("id")
    where = "row %s" % (row_id,)
    if not isinstance(posted, dict):
        problems.add("%s: expected an object, got %s" % (where, describe(posted)))
        return None

    current_keys = set(current)
    posted_keys = set(posted)
    if posted_keys != current_keys:
        parts = []
        missing = sorted(current_keys - posted_keys)
        extra = sorted(posted_keys - current_keys)
        if missing:
            parts.append("missing key(s) %s" % ", ".join(missing))
        if extra:
            parts.append("unknown key(s) %s" % ", ".join(extra))
        problems.add("%s: %s" % (where, "; ".join(parts)))
        return None

    out = {}
    ok = True
    for key, current_value in current.items():
        value = posted[key]
        field = "%s field %r" % (where, key)
        kind = value_kind(current_value)
        if kind in ("list", "dict", "other"):
            # Structured columns are not editable; keeping them byte-identical is
            # what lets the writer round-trip tables that carry nested data.
            if value != current_value:
                problems.add("%s: structured values cannot be edited" % field)
                ok = False
            out[key] = current_value
            continue
        coerced, error = coerce_value(kind, value, field)
        if error is not None:
            problems.add(error)
            ok = False
        else:
            out[key] = coerced
    return out if ok else None


def validate_rows(table, current_rows, posted_rows):
    """(rows to write, None) or (None, [messages]) - never a partial result."""
    problems = Problems()
    if not isinstance(posted_rows, list):
        return None, ["body.rows must be a list, got %s" % describe(posted_rows)]

    current_by_id = {}
    for row in current_rows:
        if not isinstance(row, dict) or "id" not in row:
            return None, [
                "config/masters_%s.json has a row without an id; refusing to write" % table
            ]
        if row["id"] in current_by_id:
            return None, [
                "config/masters_%s.json has duplicate id %s; refusing to write"
                % (table, row["id"])
            ]
        current_by_id[row["id"]] = row

    if len(posted_rows) != len(current_rows):
        return None, [
            "expected %d rows, got %d: adding or removing rows is not supported"
            % (len(current_rows), len(posted_rows))
        ]

    posted_by_id = {}
    for index, posted in enumerate(posted_rows):
        if not isinstance(posted, dict) or "id" not in posted:
            problems.add("posted row %d: missing an \"id\"" % index)
            continue
        normalized = normalize_id(posted["id"])
        key = normalized if normalized is not None else posted["id"]
        if key in posted_by_id:
            problems.add("posted row %d: duplicate id %s" % (index, posted["id"]))
            continue
        posted_by_id[key] = posted

    missing_ids = sorted(
        (row_id for row_id in current_by_id if row_id not in posted_by_id),
        key=lambda value: (isinstance(value, str), str(value)),
    )
    unknown_ids = sorted(
        (row_id for row_id in posted_by_id if row_id not in current_by_id),
        key=lambda value: (isinstance(value, str), str(value)),
    )
    if missing_ids:
        problems.add("missing row(s) for id(s): %s" % ", ".join(map(str, missing_ids)))
    if unknown_ids:
        problems.add("unknown row id(s): %s" % ", ".join(map(str, unknown_ids)))

    new_rows = []
    for current in current_rows:
        posted = posted_by_id.get(current["id"])
        if posted is None:
            continue
        row = validate_row(current, posted, table, problems)
        if row is not None:
            new_rows.append(row)

    messages = problems.result()
    if messages or len(new_rows) != len(current_rows):
        if not messages:
            messages = ["could not validate every row of config/masters_%s.json" % table]
        return None, messages
    return new_rows, None


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #


def backup_table(name, original_text):
    """Copy the current file into tools/balance/backups/ before it is replaced."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = "%s-%s" % (name, stamp)
    path = BACKUP_DIR / ("%s.json" % stem)
    suffix = 1
    while path.exists():
        path = BACKUP_DIR / ("%s-%d.json" % (stem, suffix))
        suffix += 1
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(original_text)
    return path


def write_table(name, rows):
    """Write rows atomically so a failed write can never leave a partial file."""
    path = CONFIG_DIR / ("masters_%s.json" % name)
    text = json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    tmp.replace(path)
    return text


BACKUP_NAME_RE = re.compile(r"-(\d{8}-\d{6})(?:-(\d+))?\.json$")


def backup_recency(path):
    """Order backups by when they were written.

    The name is <table>-<yyyymmdd>-<hhmmss>[-<n>].json; the collision counter of a
    same-second backup has to be compared numerically, because "-1" sorts before
    "." in the plain name and ordering by the raw file name would pick the older
    file.
    """
    match = BACKUP_NAME_RE.search(path.name)
    if match is None:
        return ("", 0)
    return (match.group(1), int(match.group(2)) if match.group(2) else 0)


def latest_backup(name):
    if not BACKUP_DIR.is_dir():
        return None
    candidates = list(BACKUP_DIR.glob("%s-*.json" % name))
    if not candidates:
        return None
    return max(candidates, key=backup_recency)


def diff_against_latest_backup(name, current_rows):
    """Field-level differences between the working file and the newest backup."""
    backup = latest_backup(name)
    if backup is None:
        return []
    try:
        with backup.open(encoding="utf-8") as handle:
            backup_rows = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(backup_rows, list):
        return []

    before = {row["id"]: row for row in backup_rows if isinstance(row, dict) and "id" in row}
    after = {row["id"]: row for row in current_rows if isinstance(row, dict) and "id" in row}

    changes = []
    for row_id in sorted(set(before) | set(after), key=lambda v: (isinstance(v, str), str(v))):
        old = before.get(row_id)
        new = after.get(row_id)
        if old is None or new is None:
            fields = sorted(set(old or new))
            for field in fields:
                changes.append(
                    {
                        "id": row_id,
                        "field": field,
                        "before": (old or {}).get(field),
                        "after": (new or {}).get(field),
                    }
                )
            continue
        for field in sorted(set(old) | set(new)):
            if old.get(field) != new.get(field):
                changes.append(
                    {
                        "id": row_id,
                        "field": field,
                        "before": old.get(field),
                        "after": new.get(field),
                    }
                )
    changes.sort(key=lambda c: (isinstance(c["id"], str), str(c["id"]), c["field"]))
    return changes


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class BalanceHandler(BaseHTTPRequestHandler):
    server_version = "BalanceTool/1.0"
    protocol_version = "HTTP/1.1"
    timeout = 60

    # -- helpers ----------------------------------------------------------- #

    def send_body(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_body(status, body, "application/json; charset=utf-8")

    def send_error_json(self, status, message):
        self.send_json(status, {"ok": False, "error": message})

    def send_file(self, path, content_type):
        try:
            body = path.read_bytes()
        except OSError as error:
            self.send_error_json(500, "could not read %s: %s" % (path, error))
            return
        self.send_body(200, body, content_type)

    def read_body(self):
        """(bytes, None) or (None, (status, message))."""
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            return None, (400, "missing Content-Length header")
        try:
            length = int(raw_length)
        except ValueError:
            return None, (400, "invalid Content-Length header")
        if length <= 0:
            return None, (400, "empty request body")
        if length > MAX_BODY_BYTES:
            return None, (413, "request body larger than %d bytes" % MAX_BODY_BYTES)
        body = self.rfile.read(length)
        if len(body) != length:
            return None, (400, "truncated request body")
        return body, None

    # -- routes ------------------------------------------------------------ #

    def do_GET(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path in ("/", "/index.html"):
            self.send_file(INDEX_FILE, "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self.send_body(204, b"", "image/x-icon")
            return
        if path == "/api/kickers":
            self.handle_kickers()
            return
        if path == "/api/discs":
            self.handle_discs()
            return
        match = TABLE_URL_RE.match(path)
        if match:
            self.handle_get_table(match.group(1))
            return
        match = DIFF_URL_RE.match(path)
        if match:
            self.handle_diff(match.group(1))
            return
        if path.startswith("/icons/"):
            self.handle_icon(path[len("/icons/"):])
            return
        self.send_error_json(404, "no route for %s" % path)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        match = TABLE_URL_RE.match(path)
        if not match:
            self.send_error_json(404, "no route for %s" % path)
            return
        self.handle_post_table(match.group(1))

    # -- endpoint bodies --------------------------------------------------- #

    def handle_kickers(self):
        try:
            kicker_rows = read_table("kicker")
            parameter_rows = read_table("kicker_parameter")
        except (OSError, ValueError, FileNotFoundError) as error:
            self.send_error_json(500, str(error))
            return
        parameters = {
            row.get("kickerId"): row for row in parameter_rows if isinstance(row, dict)
        }
        kickers = []
        for row in kicker_rows:
            if not isinstance(row, dict) or "id" not in row:
                continue
            parameter = parameters.get(row["id"], {})
            kickers.append(
                {
                    "id": row["id"],
                    "name": row.get("name") or "Kicker %s" % row["id"],
                    "weaponType": parameter.get("weaponType"),
                    "roleType": parameter.get("roleType"),
                    "skillId": parameter.get("skillId"),
                }
            )
        self.send_json(200, kickers)

    def handle_discs(self):
        try:
            disc_rows = read_table("disc")
        except (OSError, ValueError, FileNotFoundError) as error:
            self.send_error_json(500, str(error))
            return
        cards = load_disc_cards()
        discs = []
        for row in disc_rows:
            if not isinstance(row, dict) or "id" not in row:
                continue
            card = cards.get(str(row["id"])) or {}
            discs.append(
                {
                    "id": row["id"],
                    "name": row.get("name") or card.get("name") or "Disc %s" % row["id"],
                    "rarityType": row.get("rarityType"),
                    "discType": row.get("discType"),
                    "skillId": row.get("skillId"),
                    "effect": card.get("effect") or "",
                    "type": card.get("type") or "",
                    "attribute": card.get("attribute") or "",
                    "rarity": card.get("rarity") or "",
                }
            )
        self.send_json(200, discs)

    def handle_get_table(self, name):
        path = table_path(name)
        if path is None:
            self.send_error_json(404, "unknown table %r" % name)
            return
        try:
            rows = read_table(name)
        except (OSError, ValueError) as error:
            self.send_error_json(500, str(error))
            return
        self.send_json(200, rows)

    def handle_post_table(self, name):
        if table_path(name) is None:
            self.send_error_json(404, "unknown table %r" % name)
            return
        body, error = self.read_body()
        if error is not None:
            self.send_error_json(error[0], error[1])
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as decode_error:
            self.send_error_json(400, "body is not valid JSON: %s" % decode_error)
            return
        if not isinstance(payload, dict) or "rows" not in payload:
            self.send_error_json(400, "body must be an object with a \"rows\" array")
            return

        path = CONFIG_DIR / ("masters_%s.json" % name)
        with WRITE_LOCK:
            try:
                original_text = path.read_text(encoding="utf-8")
                current_rows = json.loads(original_text)
            except (OSError, ValueError) as read_error:
                self.send_error_json(500, "could not read config/masters_%s.json: %s" % (name, read_error))
                return
            if not isinstance(current_rows, list):
                self.send_error_json(500, "config/masters_%s.json is not a JSON array" % name)
                return

            rows, messages = validate_rows(name, current_rows, payload["rows"])
            if rows is None:
                self.send_error_json(400, "; ".join(messages))
                return

            try:
                backup_table(name, original_text)
            except OSError as backup_error:
                self.send_error_json(500, "could not write the backup: %s" % backup_error)
                return
            try:
                write_table(name, rows)
            except OSError as write_error:
                self.send_error_json(500, "could not write the file: %s" % write_error)
                return

        self.send_json(200, {"ok": True, "written": len(rows)})

    def handle_diff(self, name):
        if table_path(name) is None:
            self.send_error_json(404, "unknown table %r" % name)
            return
        try:
            rows = read_table(name)
        except (OSError, ValueError) as error:
            self.send_error_json(500, str(error))
            return
        self.send_json(200, {"changed": diff_against_latest_backup(name, rows)})

    def handle_icon(self, name):
        if not ICON_NAME_RE.match(name):
            self.send_error_json(404, "unknown icon %r" % name)
            return
        path = ICON_DIR / name
        if not path.is_file():
            self.send_error_json(404, "unknown icon %r" % name)
            return
        self.send_file(path, "image/png")


def build_server(port, host="127.0.0.1"):
    return ThreadingHTTPServer((host, port), BalanceHandler)


def lan_addresses():
    """IPv4 addresses of this machine's interfaces, best effort (for the URL hints only)."""
    import socket

    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Balance WebUI for config/masters_*.json")
    parser.add_argument(
        "--port", type=int, default=8765, help="TCP port to listen on (default: 8765)"
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1 = this PC only; 0.0.0.0 = every device on the LAN)",
    )
    parser.add_argument(
        "--open", action="store_true", help="open the UI in the default browser once the server is up"
    )
    args = parser.parse_args(argv)

    if not INDEX_FILE.is_file():
        print("missing %s" % INDEX_FILE, file=sys.stderr)
        return 1

    try:
        server = build_server(args.port, args.host)
    except OSError as error:
        print("could not bind %s:%d: %s" % (args.host, args.port, error), file=sys.stderr)
        return 1

    server.daemon_threads = True
    local_url = "http://127.0.0.1:%d/" % args.port
    print("Balance WebUI listening on %s" % local_url)
    if args.host == "0.0.0.0":
        for ip in lan_addresses():
            print("  from the LAN:  http://%s:%d/" % (ip, args.port))
        print("  (anyone on the network can edit the config while this runs)")
    print("editing %s (backups in %s)" % (CONFIG_DIR, BACKUP_DIR))
    print("press Ctrl+C to stop")
    sys.stdout.flush()
    if args.open:
        import webbrowser

        webbrowser.open(local_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
