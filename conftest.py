"""Root conftest — makes the repo's custom_components discoverable by the
HA loader in tests (the pytest plugin ships its own custom_components
package that would otherwise shadow ours)."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import custom_components as _cc

    ours = str(ROOT / "custom_components")
    if ours not in _cc.__path__:
        _cc.__path__.insert(0, ours)
except ImportError:  # pragma: no cover
    pass
