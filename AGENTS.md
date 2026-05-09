# Agent Rules — Boiler Room

## Versioning

The integration version in `custom_components/boiler_room/manifest.json` uses a date-time format:

```
YYYY-MM-DD_HHMM
```

The timestamp must be in **US Eastern Time** (ET).

**Before every commit**, update the `"version"` field in `manifest.json` to the current Eastern Time timestamp. Example:

```json
"version": "2026-05-09_1927"
```

Do not use semantic versioning (e.g. `1.0.0`). Always use this date-time format.
