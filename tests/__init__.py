"""Unit tests for the framework-free core of the Boiler Room integration.

The integration package imports Home Assistant at package level, and its
directory holds a `select.py` that would shadow the stdlib module if it
were put on sys.path. So the `core` subpackage is loaded by file path and
registered as the top-level package `core`. Run with:

    python -m unittest discover -s tests -t . -v
"""

import importlib.util
import sys
from pathlib import Path

_CORE_DIR = (
    Path(__file__).resolve().parent.parent / "custom_components" / "boiler_room" / "core"
)

if "core" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "core", _CORE_DIR / "__init__.py", submodule_search_locations=[str(_CORE_DIR)]
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["core"] = _module
    _spec.loader.exec_module(_module)
