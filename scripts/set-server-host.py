#!/usr/bin/env python3
"""Switch the server host/IP across configuration files and resource catalogs.

Usage:
    python scripts/set-server-host.py 192.168.1.50
    python scripts/set-server-host.py 10.0.2.2 --port 18080
    python scripts/set-server-host.py --show
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Switch server host/IP in config/server-host.json, apk-direct-server.local.json, and catalog.json."
    )
    parser.add_argument(
        "host",
        nargs="?",
        help="Host or IP address (e.g. '10.0.2.2' for emulator or '192.168.x.x' for physical device).",
    )
    parser.add_argument("--port", type=int, help="Server port (default: from config or 18080).")
    parser.add_argument("--scheme", help="URL scheme (default: http).")
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current configuration without making changes.",
    )
    parser.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Skip rebuilding the title resource catalog and fixtures.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    server_host_path = repo_root / "config" / "server-host.json"
    apk_direct_path = repo_root / "config" / "apk-direct-server.local.json"
    catalog_path = repo_root / "config" / "resources" / "catalog.json"

    # 1. Load current server-host config
    if server_host_path.exists():
        host_config = json.loads(server_host_path.read_text(encoding="utf-8-sig"))
    else:
        host_config = {
            "host": "10.0.2.2",
            "port": 18080,
            "scheme": "http",
            "description": "Host/IP used for client connections and resource catalog.",
        }

    current_host = host_config.get("host", "10.0.2.2")
    current_port = host_config.get("port", 18080)
    current_scheme = host_config.get("scheme", "http")

    if args.show or (not args.host and not args.port and not args.scheme):
        print(f"Current server host configuration ({server_host_path.name}):")
        print(f"  Host:   {current_host}")
        print(f"  Port:   {current_port}")
        print(f"  Scheme: {current_scheme}")
        print(f"  Base URL: {current_scheme}://{current_host}:{current_port}")
        return

    new_host = args.host if args.host else current_host
    new_port = args.port if args.port else current_port
    new_scheme = args.scheme if args.scheme else current_scheme

    # Update config/server-host.json
    host_config["host"] = new_host
    host_config["port"] = new_port
    host_config["scheme"] = new_scheme
    server_host_path.write_text(json.dumps(host_config, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {server_host_path.relative_to(repo_root)} -> {new_scheme}://{new_host}:{new_port}")

    # Update config/apk-direct-server.local.json
    if apk_direct_path.exists():
        apk_direct = json.loads(apk_direct_path.read_text(encoding="utf-8-sig"))
    else:
        apk_direct = {}
    apk_direct["serverBaseUrl"] = f"{new_scheme}://{new_host}:{new_port}"
    apk_direct_path.write_text(json.dumps(apk_direct, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {apk_direct_path.relative_to(repo_root)} -> serverBaseUrl: {apk_direct['serverBaseUrl']}")

    # Update config/resources/catalog.json
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        updated_count = 0
        for entry in catalog.get("resources", []):
            if "host" in entry:
                entry["host"] = new_host
                updated_count += 1
        catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Updated {catalog_path.relative_to(repo_root)}: {updated_count} resource host entries -> {new_host}")

    # Rebuild catalog & fixtures if requested
    if not args.no_rebuild:
        build_script = repo_root / "scripts" / "build-title-resource-catalog.py"
        if build_script.exists():
            print("\nRebuilding title resource catalog and fixtures...")
            result = subprocess.run([sys.executable, str(build_script)], cwd=repo_root)
            if result.returncode != 0:
                print("Warning: build-title-resource-catalog.py exited with error code", result.returncode)
            else:
                print("Title resource catalog and fixtures rebuilt successfully.")


if __name__ == "__main__":
    main()
