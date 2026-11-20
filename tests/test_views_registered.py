"""Every HomeAssistantView class defined in dashboard.py MUST be registered.

Live incident (P311): the discovery views were defined but never added to
async_register_ui's list — the page rendered, the endpoint 404'd, and the
user saw 'IS NOT showing'. This gate parses the module, finds every
HomeAssistantView subclass, and asserts each one appears in the
registration list. A defined-but-unregistered view fails the suite.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

from nspanel_core import dashboard as D  # noqa: E402


def _defined_view_classes() -> set[str]:
    """Concrete views only: classes that define their own `url =` in the
    class body. Base classes (OtaFileView, OtaUploadView,
    EntityPickerModalView, ...) carry no url — their subclasses are the
    concrete, registered ones."""
    src = (REPO / "custom_components" / "nspanel_core" / "dashboard.py").read_text()
    tree = ast.parse(src)
    views = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_match = False
        for base in node.bases:
            name = ""
            if isinstance(base, ast.Name):
                name = base.id
            elif isinstance(base, ast.Attribute):
                name = base.attr
            if (name.endswith("HomeAssistantView") or name == "OtaFileView"
                    or name.endswith("EntityPickerModalView") or name.endswith("OtaUploadView")):
                base_match = True
        if not base_match:
            continue
        has_url = any(
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "url" for t in stmt.targets)
            for stmt in node.body
        )
        # url = "" is the modal-partial base pattern (a concrete subclass
        # template fills it) — not a registrable endpoint on its own.
        empty_url = any(
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "url" for t in stmt.targets)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value == ""
            for stmt in node.body
        )
        if has_url and not empty_url:
            views.add(node.name)
    return views


def _registered_view_names() -> set[str]:
    src = (REPO / "custom_components" / "nspanel_core" / "dashboard.py").read_text()
    start = src.index("def async_register_ui")
    body = src[start:]
    end = body.index("for view_cls in views:")
    block = body[:end]
    return set(re.findall(r"^\s{8}([A-Z][A-Za-z0-9]+),", block, re.M))


def test_every_defined_view_is_registered():
    defined = _defined_view_classes()
    registered = _registered_view_names()
    missing = sorted(defined - registered)
    assert not missing, (
        f"Views defined but NOT registered (they 404 live): {missing}. "
        "Add them to the views list in async_register_ui."
    )


def test_registration_list_classes_exist():
    """A typo in the registration list (renamed/removed class) must fail
    loudly here, not 404 in production."""
    registered = _registered_view_names()
    for name in registered:
        assert hasattr(D, name), f"async_register_ui references missing class {name}"


def test_discovery_views_registered():
    registered = _registered_view_names()
    assert "DiscoveredPanelsView" in registered
    assert "DiscoveredPanelActionView" in registered
