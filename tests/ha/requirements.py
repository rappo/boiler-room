"""Print the pip requirements of the HA components the harness tests need.

pytest-homeassistant-custom-component installs Home Assistant core but not
the requirements of its components. Boiler Room depends on `conversation`
(for sentence triggers), whose requirements (hassil, home-assistant-intents,
gazetteer-matcher) must match the harness's pinned HA release exactly, so
read them from that release's manifest instead of pinning them by hand:

    python -m pip install $(python tests/ha/requirements.py)
"""

from __future__ import annotations

import json
from pathlib import Path

import homeassistant

COMPONENTS = ("conversation",)

components = Path(homeassistant.__file__).parent / "components"
requirements: list[str] = []
for name in COMPONENTS:
    manifest = json.loads((components / name / "manifest.json").read_text())
    requirements.extend(manifest.get("requirements", []))
print(" ".join(requirements))
