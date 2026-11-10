# Installing NSPanel Manager HA on Home Assistant

This guide covers installing the add-on on a Home Assistant OS or Home Assistant
Supervised installation. If you run plain Docker (e.g. on a NAS), jump to
[Option B: Docker / NAS](#option-b-docker-nas).

---

## What you need

| Requirement | Notes |
|---|---|
| Home Assistant OS or Supervised | The add-on needs the Supervisor (any Raspberry Pi, generic x86, or VM). HA Container users: use [Option B](#option-b-docker-nas). |
| MQTT broker | The panels and the manager talk over MQTT. The [Mosquitto broker add-on](https://github.com/home-assistant/addons/tree/master/mosquitto) is the easiest choice. |
| Sonoff NSPanel(s) | The original NSPanel (not NSPanel Pro), flashed by the manager itself — you do **not** need ESPHome or any pre-flashing. |
| Network | Panels and the HA host must be on the same LAN/VLAN as your panels. |

---

## Option A: Home Assistant add-on (recommended)

### 1. Add the add-on repository

In Home Assistant:

1. Open **Settings → Add-ons → Add-on Store**.
2. Click the **⋮** menu (top right) → **Repositories**.
3. Paste this URL and click **Add**:

   ```
   https://github.com/ALeXXBody/NSPanelManager-HA
   ```

4. Close the dialog. A new repository **NSPanel Manager HA** appears with two add-ons:
   - **NSPanel Manager HA** (stable)
   - **NSPanel Manager HA BETA** (development builds — skip unless testing)

### 2. Install and start

1. Click **NSPanel Manager HA → Install**. The image is pulled from GHCR
   (built automatically for i386/amd64/armhf/armv7/aarch64 when a release is published).
2. Set **Start on boot** and **Watchdog** to on (both are defaults), then click **Start**.
3. Click **Open Web UI** (or the **fit-to-screen** icon that appears in your HA sidebar).

### 3. First-run configuration

The manager opens its initial-setup wizard at `http://<ha-host>:8000/`:

1. **Manager settings** — leave the defaults unless you changed ports.
2. **MQTT** — enter your broker address (e.g. `core-mosquitto` when using the
   Mosquitto add-on on the same HA instance), port `1883`, and a username/password
   you created in Mosquitto.
3. **Home Assistant** — nothing to do. The add-on injects `SUPERVISOR_TOKEN`
   automatically (`IS_HOME_ASSISTANT_ADDON=true`), so the manager talks to your HA
   instance's API out of the box — no long-lived access token needed.
4. Finish the wizard.

> **Verify the MQTT connection**: open the manager's log (port 8000 → About → logs)
> and look for "Connected to MQTT". If it fails, double-check broker address and
> credentials.

### 4. Prepare Home Assistant entities

The manager reads entities from HA over the API. In HA, make sure the entities you
want on panels exist (lights, switches, scenes, a temperature sensor for the
screensaver if you want outside temperature).

### 5. Register and flash your panel

1. Power on the NSPanel. On first boot it starts its own access point
   (`NSPanelManager_XXXXXX`) — join it from a phone/laptop, enter your WiFi
   credentials and the manager address (`http://<ha-host>:8000`).
2. The panel appears under **Denied NSPanels** in the manager UI — click **Accept**.
3. In the panel's edit page, click **Flash firmware** / **Update TFT**. The manager
   pushes the firmware and the screen UI to the panel automatically.
4. Create rooms, add entities to pages, arrange them, and they show up on the panel.

### 6. Home Assistant integration niceties

- Panel buttons can be mapped to HA entities ("detached mode") in the panel settings.
- The panel reports temperature/humidity over MQTT — build a sensor from the
  `nspanel/.../temperature` topics if you want them in HA.
- Panels send status (IP, RSSI, heap) back to the manager; check the web UI for
  signal problems.

---

## Option B: Docker / NAS

For HA **Container** installs or running on a NAS next to HA:

```bash
# Build the image (multi-stage; builds the UI and the C++ bridge in-tree)
cd docker
docker build -t nspanelmanager-ha .

# Run (adjust paths to persistent storage)
docker run -d --name nspanelmanager-ha \
  -p 8000:8000 \
  -v /your/data/dir:/data \
  --restart unless-stopped \
  nspanelmanager-ha
```

Differences from the add-on:

- Create a **long-lived access token** in HA (Profile → Security → Long-lived
  access tokens) and paste it in the manager's Settings → Home Assistant, with
  address `http://<ha-host>:8123`.
- Set the environment variable `IS_HOME_ASSISTANT_ADDON=false` (default) — the
  supervisor-token auto-configuration is add-on only.
- On TrueNAS SCALE note: builds inside the appliance's podman sandbox can fail
  with read-only `/proc/sys` — build the image on a regular Docker host or via
  CI (the repo's GitHub Actions publish multi-arch images to GHCR on release).

---

## Updating

- **Add-on**: HA shows an update badge when a new release is published here —
  Settings → Add-ons → NSPanel Manager HA → Update.
- **Docker**: pull/rebuild the image and recreate the container. Config
  (SQLite database, uploaded firmware) lives in the mounted `/data` volume.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Add-on not visible in the store | Make sure the repository URL was added exactly as above and you have HA OS/Supervised (not Container). |
| Add-on fails to install, "image not found" | A GitHub release with published images is required; alternatively remove the `image:` line from `docker/config.yaml` so the Supervisor builds the image on the HA host itself (slower first start). |
| "Could not connect to Home Assistant" | Add-on: check the add-on logs for token errors and restart it (the supervisor token is injected at start). Docker: verify the long-lived token and the HA URL (must include `http://` and port `8123`). |
| Panels never appear in the manager | Check panel got WiFi + manager address via its AP; check MQTT broker reachable from BOTH panel and manager; check the panel's MAC is not sitting in Denied list. |
| Wrong temperature displayed | Set the temperature provider to a Home Assistant sensor in the room's settings (OpenHAB was removed in this fork). |
| TFT update stuck | Keep the panel powered, updates stream 4 KB chunks with ACK verification; if it fails, the manager retries automatically. |

## Architecture notes

- The manager does **not** sit between HA and your devices: your devices keep
  working through HA directly. The manager only renders/waits panel UIs and
  forwards panel actions into HA.
- The web UI (React) connects to the C++ bridge on port 8002 (STOMP over
  WebSocket) for realtime updates; the Django app on 8000 handles configuration.
