"""P311: the panel-broker MQTT credentials are editable AFTER the first run
(Settings → Panel MQTT). The first-run page is a one-time gate, but the
credentials are live settings — the user's install had first_run_done set
without ever saving them, and the accept action then had nothing to send
(409 'First-run settings missing', invisible in a tooltip). These tests pin
the settings path and the visible-error contract."""

from __future__ import annotations

import asyncio
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "custom_components"))

import pytest  # noqa: E402

from nspanel_core import manager as M  # noqa: E402
from nspanel_core.models import GlobalSettings  # noqa: E402


def test_validate_settings_accepts_panel_broker_fields():
    clean, errors = M.NSPanelCoreManager.validate_settings({
        "panel_broker_host": "192.168.50.20",
        "panel_broker_port": "1883",
        "panel_broker_user": "ALeXX",
        "panel_broker_pass": "pw",
    })
    assert not errors
    assert clean["panel_broker_host"] == "192.168.50.20"
    assert clean["panel_broker_port"] == 1883
    assert clean["panel_broker_user"] == "ALeXX"
    assert clean["panel_broker_pass"] == "pw"


def test_validate_settings_rejects_bad_broker_host():
    clean, errors = M.NSPanelCoreManager.validate_settings({
        "panel_broker_host": "http://evil",
    })
    assert "panel_broker_host" in errors


def test_validate_settings_allows_empty_user_and_pass():
    """A broker that allows anonymous gets empty user/pass on purpose."""
    clean, errors = M.NSPanelCoreManager.validate_settings({
        "panel_broker_host": "192.168.50.20",
        "panel_broker_user": "",
        "panel_broker_pass": "",
    })
    assert not errors
    assert clean["panel_broker_host"] == "192.168.50.20"
    assert clean["panel_broker_user"] == ""
    assert clean["panel_broker_pass"] == ""


def test_apply_settings_persists_broker_credentials():
    import asyncio

    mgr = MagicMock()
    mgr.config.settings = GlobalSettings()
    mgr.async_save = AsyncMock()

    # MagicMock self shadows class methods — bind the real validators and
    # async collaborators
    mgr.validate_settings = lambda ui, cur=None: M.NSPanelCoreManager.validate_settings(ui, cur)
    mgr._publish_manager_status = AsyncMock()
    mgr._reschedule_weather = lambda: None

    async def run():
        errors = await M.NSPanelCoreManager.apply_settings(mgr, {
            "panel_broker_host": "192.168.50.20",
            "panel_broker_port": "1883",
            "panel_broker_user": "ALeXX",
            "panel_broker_pass": "pw",
        })
        return errors

    errors = asyncio.new_event_loop().run_until_complete(run())
    assert not errors
    s = mgr.config.settings
    assert s.panel_broker_host == "192.168.50.20"
    assert s.panel_broker_port == 1883
    assert s.panel_broker_user == "ALeXX"
    assert s.panel_broker_pass == "pw"
    mgr.async_save.assert_awaited()


def test_settings_context_exposes_broker_fields():
    """The general tab renders the stored values (host/port/user) and only
    a HINT for the password (never the secret itself)."""
    import jinja2

    from nspanel_core import dashboard as D
    tpl_dir = D.TEMPLATES_DIR
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(tpl_dir)),
                             undefined=jinja2.ChainableUndefined)
    tpl = env.get_template("_tab_general.html")
    html = tpl.render(
        manager_address="core", manager_port=8000,
        panel_broker_host="192.168.50.20", panel_broker_port=1883,
        panel_broker_user="ALeXX", panel_broker_pass_placeholder="(saved)",
    )
    assert 'name="panel_broker_host"' in html
    assert 'value="192.168.50.20"' in html
    assert 'name="panel_broker_user"' in html
    assert "ALeXX" in html
    assert 'name="panel_broker_pass"' in html
    assert 'type="password"' in html
