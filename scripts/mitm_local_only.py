"""mitmproxy addon that permits only local, first-party fixture handling.

Every decrypted request is either rewritten to the loopback fixture server or
answered locally.  The addon never preserves an Internet destination.
"""

import os

from mitmproxy import http


FIRST_PARTY_HOSTS = {
    "kickflight-api.grenge.jp",
    "colorful-api-octo-sb.grenge.jp",
    "kickflight-resource-api.grenge.jp",
}
BACKEND_HOST = os.environ.get("KICKFLIGHT_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("KICKFLIGHT_BACKEND_PORT", "18080"))


def request(flow: http.HTTPFlow) -> None:
    original_host = flow.request.pretty_host.lower().rstrip(".")

    if original_host not in FIRST_PARTY_HOSTS:
        flow.response = http.Response.make(
            451,
            b"Blocked by the Kick-Flight local-only harness.\n",
            {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"},
        )
        return

    # Route the request to Kestrel while retaining the original Host header so
    # the strict host/method/path fixture matcher can select the right response.
    flow.request.scheme = "http"
    flow.request.host = BACKEND_HOST
    flow.request.port = BACKEND_PORT
    flow.request.headers["Host"] = original_host
