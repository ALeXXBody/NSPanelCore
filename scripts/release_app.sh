#!/usr/bin/env bash
# P370: the app-release discipline in ONE command.
#
# Why this exists: on 2026-11-27 the integration shipped releases WITHOUT
# the zip asset HACS's update entity installs from — the installs silently
# did nothing (the files never landed on the HA box), the navbar kept
# showing an old version, and the mixed fw-*/app-* tag prefixes made HACS
# rank releases wrongly so the UI nagged "update available" forever.
#
# What this enforces for every app release:
#   1. the working tree is committed and pushed BEFORE the release
#   2. the tag = the commit whose tree the zip is built from (git archive —
#      the zip can never drift from the tag)
#   3. the zip asset (custom_components/nspanel_core/ at the root) is
#      UPLOADED — HACS installs from the asset, not from "the repo"
#   4. the firmware tags stay PRERELEASES — HACS must never offer them as
#      integration updates
#
# Usage: scripts/release_app.sh <version> [title] [notes-file]
#   (version without the app- prefix, e.g. 0.3.19)
set -euo pipefail

VER="${1:?usage: release_app.sh <version> [title] [notes-file]}"
TAG="app-v$VER"
TITLE="${2:-NSPanel Core $VER}"
NOTES="${3:-}"

cd "$(dirname "$0")/.."

# 1. everything committed
if [ -n "$(git status --porcelain)" ]; then
  echo "ERROR: the working tree is dirty — commit first." >&2
  exit 1
fi
git fetch origin main --quiet
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "ERROR: main is not in sync with origin — push first." >&2
  exit 1
fi

# 2. the manifest carries this version
MANIFEST_VER=$(python3 -c "import json; print(json.load(open('custom_components/nspanel_core/manifest.json'))['version'])")
if [ "$MANIFEST_VER" != "$VER" ]; then
  echo "ERROR: manifest.json says $MANIFEST_VER, releasing $VER — bump it first." >&2
  exit 1
fi

# 3. the tag + the zip FROM THE TAG (never drift)
git tag -f "$TAG" "$LOCAL"
git push origin "$TAG" --quiet
git archive "$TAG" --format=zip --output "/tmp/nspanel_core-$VER.zip" \
  custom_components/nspanel_core
echo "zip: $(du -h "/tmp/nspanel_core-$VER.zip" | cut -f1)"

# 4. the release WITH the asset
if [ -n "$NOTES" ]; then
  gh release create "$TAG" "/tmp/nspanel_core-$VER.zip" \
    --title "$TITLE" --notes-file "$NOTES"
else
  gh release create "$TAG" "/tmp/nspanel_core-$VER.zip" \
    --title "$TITLE" --notes "NSPanel Core $VER"
fi
echo "released $TAG (with the zip asset)"
