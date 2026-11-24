# Releasing NSPanel Core — the rule

**An app release is cut ONLY when integration code changes**
(`custom_components/nspanel_core/**/*.py`, `ui/`, `www/`, config/manifest
semantics). Firmware changes NEVER trigger an app release, ever.

**Publishing panel firmware (ESP + data fs + TFT):**
The firmware release flow (current): the artifacts land in `firmware/releases/vX/`, `firmware/manifest.json` is bumped (the evergreen raw URLs the panel fetches), the bundled copies under `custom_components/nspanel_core/firmware/` are updated, and the recovery set is regenerated. The old `firmware/publish.sh <version>` — uploads the 6 OTA files to the evergreen
`firmware-latest` release (stable URLs, overwritten in place) and commits
the updated `firmware/manifest.json` to `main`. Panels fetch it from there.
No tag. No HACS release. No version bump in `hacs.json`.

**Cutting an app release (integration changes only):**
bump `hacs.json` + `custom_components/nspanel_core/manifest.json`
(patch for fixes, minor for features), tag `vX.Y.Z`, `gh release create`.
The tag exists so HACS can install that code state — nothing else.

History note: v1.3.28 was cut for a firmware-only change and has been
deleted (release + tag). It must not be recreated or used as precedent.
