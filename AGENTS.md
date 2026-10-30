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

## Voice sentences

There is no automation, blueprint or button: `voice.py` registers one conversation trigger with `get_agent_manager(hass).register_trigger(sentences, callback)` (that signature exists from HA 2026.3.0 on, which is `hacs.json`'s floor; `conversation` is in `manifest.json` dependencies so it is set up first) and unregisters it on unload. The trigger is rebuilt on every entry setup, unload and options change from `core/sentences.py` `build_commands({entry_id: nicknames})`, which returns every template with its handler, static params and target entry. The callback looks the matched template text up in that list and calls the handler in `services.py` directly; the handler's `speech` is the Assist response.

Rules that follow from how HA matches:

- **Template order is behavior.** hassil yields matches in template order and HA keeps the first per trigger, so anchored sentences (`... on Jellyfin`, `... on the <device>`, `the X app`) must come before the generic `(Launch|Play) {game_name}`. `tests/test_sentences.py` runs real hassil over the templates; add a case there for any new sentence that could overlap.
- Every `{slot}` is a wildcard. Slot names map to handler keywords in `SLOT_TO_KWARG`.
- A nickname two devices share is registered as an "ambiguous device" sentence that asks which device, never fired for both.
- Nicknames are an options field per entry (`device_nicknames`); blank means the defaults (`default_nicknames(device_name)`).

## Testing

Run both before every commit; CI runs them on every push and PR.

```bash
cd agent && gofmt -l . && go vet ./... && go test ./...
python -m pip install aiohttp hassil && python -m unittest discover -s tests -t . -v
python -m pip install pytest-homeassistant-custom-component && python -m pip install $(python tests/ha/requirements.py) && python -m pytest tests/ha -q
```

- `tests/` (plain unittest) covers `core/`. It loads `core` by file path (see `tests/__init__.py`). Never put `custom_components/boiler_room` itself on `sys.path`: its `select.py` shadows the stdlib `select` module and breaks `asyncio` (cost a round of head-scratching on 2026-10-29).
- `hassil` (Assist's matcher) is only needed by `tests/test_sentences.py`, which skips its matching cases without it; CI installs it so they always run there.
- `tests/ha/` (pytest + `pytest-homeassistant-custom-component`) sets the integration up in a real Home Assistant core with the agent mocked, for behavior that lives in HA wiring (coordinator, entities, storage, the sentence trigger). The harness installs HA core but not component requirements; `tests/ha/requirements.py` prints the ones `conversation` (a Boiler Room dependency) needs for the harness's pinned HA release, and `conftest.py` sets up the `homeassistant` component because `conversation` reads its exposed-entities store. The harness pins its own HA release, and its Python floor follows HA's (3.14 since HA 2026.3). On an older Python, pip does not fail: it quietly resolves the last harness that supports it, so confirm `pip list | grep homeassistant` shows the release you mean before trusting a run. It is a correctness check, not a compatibility check. Under pytest the harness's own `custom_components` package shadows this repo's; `tests/ha/conftest.py` appends this repo's directory to its `__path__`, which is why those tests only run through pytest from the repo root.
- New pure logic goes in `core/` with a unittest beside it; new HA wiring gets a harness test; anything that touches the Steam machine itself (pactl, steamosctl, DBus) is verified live.

## Lessons

- 2026-10-29: the WebSocket reconnect cap was reverted from 5 s to 30 s by a README commit that pasted an old copy of `__init__.py`. Keep behavior changes and doc changes in separate commits.
- 2026-10-30: CI pinned Python 3.13, so pip resolved the last harness that supported it (HA 2026.2.3) and every harness test failed with `register_trigger() got an unexpected keyword argument 'sentences'`. That form (`sentences=`, `trigger_callback=`) exists from HA 2026.3.0 on; 2025.10 to 2026.2 take a `TriggerDetails` object and earlier releases have no `register_trigger` on the agent manager at all. `hacs.json`'s floor is 2026.3.0 for that reason: a floor is a claim about the oldest API the code calls, so check it against the release's source, not against when a feature first appeared.
- 2026-10-29: `du -sb $HOME` ran on every 15 s poll (3.8 s per call on the Steam machine). Anything that walks the disk goes behind `DirSizeSampler` or an equivalent cache.
