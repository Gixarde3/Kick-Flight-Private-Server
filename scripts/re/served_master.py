"""Fetch and decrypt a served master table: python scripts/re/served_master.py Weapon [--host 127.0.0.1:18080]"""
import sys, json, urllib.request
from Crypto.Cipher import AES
name = sys.argv[1]; host = sys.argv[3] if len(sys.argv) > 3 else "127.0.0.1:18080"
req = urllib.request.Request(f"http://{host}/demo-master/{name}", headers={"Host": "192.168.68.55:18080"})
body = urllib.request.urlopen(req).read()
key = b"1a837b9ee2ae11a07a0f529a4cd4b61c"
pt = AES.new(key, AES.MODE_CBC, body[:16]).decrypt(body[16:]); pt = pt[:-pt[-1]]
rows = json.loads(pt)
for r in rows: print(json.dumps(r, ensure_ascii=False))
