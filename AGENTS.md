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

## Intents, tools and voice sentences

Every action is described once, in `services.py` `ACTIONS` (handler, fields, LLM description, annotation flags), and reaches users through three layers. One code path: a command from any of them ends in the action's intent handler.

- **Intents** (`intents.py`): one `BoilerRoomIntentHandler` per action, intent types `BoilerRoom...`, registered with `intent.async_register` when the first config entry loads and removed when the last unloads. `platforms` stays `None` so they are handled whatever entities are exposed. The optional `device` slot takes a name, a nickname or a config entry id (what the sentence lane passes). Left out: an action that changes one device goes to the only device or answers with a `NO_VALID_TARGETS` error asking which one; Jellyfin actions pick the device with Jellyfin configured; read-only actions report on every device.
- **LLM tools** (`llm.py`): registering an intent exposes nothing to LLMs. Home Assistant (2026.8+) imports an integration's `llm.py` by name and calls `async_get_tools(hass, llm_context, api_id)`; for `LLM_API_ASSIST` it returns one `IntentTool` per handler, named `boiler_room__<IntentType>` (the prefix HA requires), with `integration=DOMAIN` and `ToolAnnotations` from the action table, plus a prompt line naming the devices. That is what Ollama/OpenAI conversation agents with the Assist API, and the MCP Server integration, see. `conversation`, `intent` and `llm` are in `manifest.json` dependencies.
- **Voice sentences** (`voice.py`, templates in `core/sentences.py`): `get_agent_manager(hass).register_trigger(sentences, callback)` is the only way an integration can give the default agent sentences, and triggers run before any conversation agent in every pipeline, so this is the fast offline lane. The callback owns no command logic: it maps the matched template to the action's intent type and slots (`intent_slots`), adds the entry the spoken nickname belongs to as the `device` slot, and calls `intent.async_handle`; the response speech is the Assist answer. The trigger is rebuilt on every entry setup, unload and options change. The templates are the core phrasings in the README's tables only; free phrasing is the LLM lane's job, so a new phrasing goes to the README table or nowhere.

Rules that follow from how HA matches:

- **Template order is behavior.** hassil yields matches in template order and HA keeps the first per trigger, so anchored sentences (`... on Jellyfin`, `... on the <device>`, `the X app`) must come before the generic `(Launch|Play) {game_name}`. `tests/test_sentences.py` runs real hassil over the templates; add a case there for any new sentence that could overlap.
- Every `{slot}` is a wildcard. Slot names map to intent slot (service field) names in `SLOT_TO_FIELD`.
- A nickname two devices share is registered as an "ambiguous device" sentence that asks which device, never fired for both. The same rule applies to the `device` slot: `match_device` lets a device's own name win over another device's nickname.
- Nicknames are an options field per entry (`device_nicknames`); blank means the defaults (`default_nicknames(device_name)`).
- Schemas use `probatio`, the validation library HA ships; `voluptuous` left HA's requirements in 2026 and is only installed by accident. A probatio marker's `description=` becomes the parameter help in the LLM tool schema.

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

- 2026-10-30: registering an intent (`intent.async_register`) exposes nothing to LLM agents or the MCP Server. In HA 2026.8+ an integration ships a `llm.py` platform with `async_get_tools`; without it the intents only serve the sentence trigger and the HTTP intent API. `ToolAnnotations` and `IntentTool(integration=, annotations=)` are 2026.10.0+, which is why `hacs.json`'s floor moved from 2026.3.0 to 2026.10.0 (checked against the release tags on GitHub, not the changelog).
- 2026-10-30: HA 2026.10 no longer requires `voluptuous`; it ships `probatio`. The service schemas imported voluptuous and worked only because other packages still pull it in. Slot schemas must be probatio: an `IntentHandler` wraps each slot in a `probatio.Schema`, which does not recognize voluptuous markers.

- 2026-10-29: the WebSocket reconnect cap was reverted from 5 s to 30 s by a README commit that pasted an old copy of `__init__.py`. Keep behavior changes and doc changes in separate commits.
- 2026-10-30: CI pinned Python 3.13, so pip resolved the last harness that supported it (HA 2026.2.3) and every harness test failed with `register_trigger() got an unexpected keyword argument 'sentences'`. That form (`sentences=`, `trigger_callback=`) exists from HA 2026.3.0 on; 2025.10 to 2026.2 take a `TriggerDetails` object and earlier releases have no `register_trigger` on the agent manager at all. `hacs.json`'s floor was 2026.3.0 for that reason (2026.10.0 since the LLM tools): a floor is a claim about the oldest API the code calls, so check it against the release's source, not against when a feature first appeared.
- 2026-10-29: `du -sb $HOME` ran on every 15 s poll (3.8 s per call on the Steam machine). Anything that walks the disk goes behind `DirSizeSampler` or an equivalent cache.
