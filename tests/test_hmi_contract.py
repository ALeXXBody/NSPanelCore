"""Step 5 contract — the HMI lives in-repo as nxwright TEXT source, checks
clean, and the source carries the NSPanel Core identity."""

from __future__ import annotations

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
HMI = ROOT / "custom_components/nspanel_core/hmi_kit"


def test_hmi_source_layout():
    assert (HMI / "program.nx").is_file()
    assert (HMI / "app.toml").is_file()
    assert (HMI / "defaults.toml").is_file()
    assert (HMI / "pages").is_dir()
    assert (HMI / "fonts").is_dir()
    assert (HMI / "pictures").is_dir()


def test_hmi_no_binary_blobs_committed():
    """The .tft is a release artifact — the source tree must not carry one."""
    for p in HMI.rglob("*.tft"):
        pytest.fail(f"compiled TFT committed in source tree: {p}")


def test_nxwright_check_clean():
    """The source must pass the toolchain's own validation."""
    r = subprocess.run(["nxwright", "check", str(HMI)],
                       capture_output=True, text=True, timeout=300)
    out = (r.stdout + r.stderr).strip()
    assert "0 errors, 0 warnings" in out, f"nxwright check not clean: {out}"


def test_nxwright_build_emits_project():
    """The build step (source → .HMI) must succeed end to end."""
    import tempfile
    out = pathlib.Path(tempfile.mkdtemp()) / "verify.hmi"
    r = subprocess.run(["nxwright", "build", str(HMI), str(out), "--overwrite"],
                       capture_output=True, text=True, timeout=600)
    assert out.is_file() and out.stat().st_size > 1_000_000, (
        f"build produced nothing usable: {r.stdout} {r.stderr}"
    )
