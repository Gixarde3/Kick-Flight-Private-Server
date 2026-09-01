# Fixture format

Each JSON file maps exactly one `host + method + path` tuple to a local response. Files are re-read when their timestamp or length changes; recompilation is unnecessary.

`body` is UTF-8 text and `bodyBase64` is binary. They are mutually exclusive. Unknown routes return a local strict-mode error and are never forwarded.

The three committed `__fixture-probe` fixtures test harness capabilities only. They are not claims about the original game protocol. Client contracts must be added only after a captured request and DTO evidence identify them.

The accepted Phase 1 client contracts are `boot-index.accepted.json` and `resource-list-12345.json`. The synthetic Octo version `12345` scopes the reconstructed minimum title catalog to this local harness; it is not claimed to be a historical production version. Rebuild it with `scripts/build-title-resource-catalog.ps1` after the direct server IP changes.
