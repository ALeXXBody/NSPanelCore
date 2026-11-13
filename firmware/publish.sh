#!/bin/bash
# Publish panel firmware WITHOUT an app release.
# Usage: ./publish.sh <version>   (e.g. ./publish.sh 0.1.160)
# 1. You build the binaries first (pio run / buildfs / build_image.sh) and
#    copy them into custom_components/nspanel_core/firmware/{sonoff,custom}/
#    and the TFTs into custom_components/nspanel_core/tft/.
# 2. This script uploads the 6 OTA files to the evergreen `firmware-latest`
#    release (stable URLs, overwritten in place), refreshes
#    firmware/manifest.json (version + md5s + notes) and commits it to main.
# Panels pick the new firmware up via the integration's Check/Download flow.
set -e
VERSION="${1:?usage: ./publish.sh <version, e.g. 0.1.160>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INT="$REPO_ROOT/custom_components/nspanel_core"
NOTES="${2:-}"
TMP=$(mktemp -d)
cp "$INT/firmware/sonoff/firmware.bin"   "$TMP/sonoff-firmware.bin"
cp "$INT/firmware/sonoff/data_file.bin" "$TMP/sonoff-data_file.bin"
cp "$INT/firmware/custom/firmware.bin"   "$TMP/custom-firmware.bin"
cp "$INT/firmware/custom/data_file.bin" "$TMP/custom-data_file.bin"
cp "$INT/tft/gui.tft"                    "$TMP/gui.tft"
cp "$INT/tft/gui_us.tft"                 "$TMP/gui_us.tft"
gh release upload firmware-latest --clobber \
  "$TMP/sonoff-firmware.bin" "$TMP/sonoff-data_file.bin" \
  "$TMP/custom-firmware.bin" "$TMP/custom-data_file.bin" \
  "$TMP/gui.tft" "$TMP/gui_us.tft"
rm -rf "$TMP"
BASE="https://github.com/ALeXXBody/NSPanelCore/releases/download/firmware-latest"
python3 - "$VERSION" "$NOTES" <<'PY'
import hashlib, json, sys
version, notes = sys.argv[1], sys.argv[2]
base = "https://github.com/ALeXXBody/NSPanelCore/releases/download/firmware-latest"
def md5(p):
    h = hashlib.md5()
    with open("custom_components/nspanel_core/" + p, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()
asset = {
    "firmware/sonoff/firmware.bin": "sonoff-firmware.bin",
    "firmware/sonoff/data_file.bin": "sonoff-data_file.bin",
    "firmware/custom/firmware.bin": "custom-firmware.bin",
    "firmware/custom/data_file.bin": "custom-data_file.bin",
    "tft/gui.tft": "gui.tft",
    "tft/gui_us.tft": "gui_us.tft",
}
man = {"version": version, "notes": notes, "files": {}}
for key, name in asset.items():
    man["files"][key] = {"url": f"{base}/{name}", "md5": md5(key)}
json.dump(man, open("firmware/manifest.json", "w"), indent=2)
print("manifest rewritten for", version)
PY
# Re-download every asset and verify it matches the manifest before committing:
# a partial/clobbered upload must never become the published manifest.
python3 - "$VERSION" <<'PY'
import hashlib, json, sys, urllib.request
version = sys.argv[1]
man = json.load(open("firmware/manifest.json"))
for key, entry in man["files"].items():
    h = hashlib.md5()
    req = urllib.request.Request(entry["url"], headers={"User-Agent": "NSPanelCore-publish/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            h.update(chunk)
    if h.hexdigest() != entry["md5"]:
        print(f"VERIFY FAILED: {key} served {h.hexdigest()} != manifest {entry['md5']}", file=sys.stderr)
        sys.exit(1)
    print(f"verified {key}")
PY
echo "$VERSION" > "$REPO_ROOT/custom_components/nspanel_core/firmware/version"
git -C "$REPO_ROOT" add firmware/manifest.json custom_components/nspanel_core/firmware/version
git -C "$REPO_ROOT" commit -m "Publish firmware $VERSION (no app release)"
git -C "$REPO_ROOT" push origin HEAD
echo "Published firmware $VERSION."
