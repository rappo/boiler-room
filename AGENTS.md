# Agent Rules — Boiler Room

## Versioning

The integration version in `custom_components/boiler_room/manifest.json` uses **CalVer** format:

```
YYYY.M.D
```

**Before every commit**, update the `"version"` field in `manifest.json` to today's date. Example:

```json
"version": "2026.5.9"
```

Do not use semantic versioning (e.g. `1.0.0`). Always use CalVer. If multiple releases happen on the same day, append a patch number: `2026.5.9.1`, `2026.5.9.2`, etc.

## Layout

- `custom_components/boiler_room/` is the HA integration. Its `core/` subpackage is **framework-free**: nothing in it may import `homeassistant`. Matching, Jellyfin request building and the phonetic cache live there so they can be unit-tested without an HA install.
- `agent/` is the Go agent that runs on the SteamOS device.

## Testing

Run both before every commit; CI runs them on every push and PR.

```bash
cd agent && gofmt -l . && go vet ./... && go test ./...
python -m pip install aiohttp && python -m unittest discover -s tests -t . -v
```

- Python tests load `core` by file path (see `tests/__init__.py`). Never put `custom_components/boiler_room` itself on `sys.path`: its `select.py` shadows the stdlib `select` module and breaks `asyncio` (cost a round of head-scratching on 2026-10-29).
- New pure logic goes in `core/` with a test beside it in `tests/`. HA-facing code (entities, services, config flow) is verified by deploying to HA.

## Lessons

- 2026-10-29: the WebSocket reconnect cap was reverted from 5 s to 30 s by a README commit that pasted an old copy of `__init__.py`. Keep behavior changes and doc changes in separate commits.
- 2026-10-29: `du -sb $HOME` ran on every 15 s poll (3.8 s per call on the Steam machine). Anything that walks the disk goes behind `DirSizeSampler` or an equivalent cache.
