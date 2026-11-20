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
from nspanel_core import dashboard as D  # noqa: E402
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


def test_blank_password_keeps_stored_one():
    """The settings form always posts every field — an untouched empty
    password box must NOT wipe the stored credential (a later save of any
    setting would otherwise break provisioning silently)."""
    clean, errors = M.NSPanelCoreManager.validate_settings(
        {"panel_broker_pass": ""},
        current={"panel_broker_pass": "existing-pw"},
    )
    assert not errors
    assert "panel_broker_pass" not in clean  # absent = keep existing


def test_blank_password_wipes_when_none_stored():
    clean, errors = M.NSPanelCoreManager.validate_settings(
        {"panel_broker_pass": ""}, current={},
    )
    assert not errors
    assert clean["panel_broker_pass"] == ""


def test_nonempty_password_overwrites():
    clean, errors = M.NSPanelCoreManager.validate_settings(
        {"panel_broker_pass": "new-pw"}, current={"panel_broker_pass": "old"},
    )
    assert not errors
    assert clean["panel_broker_pass"] == "new-pw"


def test_push_body_survives_non_ascii_password():
    r"""The panel's parser rejects \uXXXX escapes (exotic) — the manager must
    never emit them: ensure_ascii=False, UTF-8 body."""
    import json as _json

    class _S:
        panel_broker_host = "192.168.50.20"
        panel_broker_port = 1883
        panel_broker_user = "ALeXX"
        panel_broker_pass = "Pässwörd"

    body = D._broker_push_body(_S()).decode("utf-8")
    assert "\\u" not in body
    assert "Pässwörd" in body
    # and the panel parser accepts it round-trip is pinned by the firmware
    # host suite; here we pin the manager never escapes non-ASCII
    parsed = _json.loads(body)
    assert parsed["mqtt_pass"] == "Pässwörd"
