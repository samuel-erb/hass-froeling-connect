"""Make the integration's HA-independent modules importable without Home Assistant.

``custom_components/froeling_connect/__init__.py`` imports Home Assistant, which is
not needed to test the API parser and the migration planner. Register the
package with its ``__path__`` only, so submodules import without running it.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = ROOT / "custom_components" / "froeling_connect"

for name, path in (("custom_components", ROOT / "custom_components"), ("custom_components.froeling_connect", PACKAGE_DIR)):
    if name not in sys.modules:
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
