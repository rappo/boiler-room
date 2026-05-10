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
