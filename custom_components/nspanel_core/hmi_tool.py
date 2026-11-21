"""P312: the nxwright toolchain, vendored INSIDE the integration.

The studio's Send compiles the design with nxwright — the manager runs
inside the Home Assistant environment, where the tool does not exist (it
was installed only on the development host). nxwright is NOT on PyPI, so a
manifest requirement cannot fetch it — the package is vendored here
(Apache-2.0/OFL, license file included) and loaded from this directory.
"""
from __future__ import annotations

import pathlib
import sys

VENDORED_DIR = pathlib.Path(__file__).resolve().parent / "nxwright"


def ensure_toolchain() -> None:
    """Put the vendored nxwright FIRST on sys.path (before any site-packages
    copy that may or may not exist in the HA environment)."""
    d = str(VENDORED_DIR)
    if d in sys.path:
        return
    sys.path.insert(0, d)
