# 1. Installation

NSPanel Core ships as a Home Assistant custom integration delivered through
HACS.

![The NSPanels page](https://raw.githubusercontent.com/wiki/ALeXXBody/NSPanelCore/nspanels.png)

## What you need

- A flashed NSPanel (the panel runs the NSPanel Core native firmware — it
  registers itself the moment it joins your network)
- Home Assistant 2024.x or newer
- An MQTT broker reachable by both Home Assistant and the panel

## Steps

1. In Home Assistant, open **HACS → Integrations** and add this repository
   as a custom repository (category: *Integration*).
2. Install **NSPanel Core** and **restart Home Assistant** when prompted.
   The integration's code only loads at startup — the restart is required
   after every update.
3. After the restart, open the manager: **the sidebar → NSPanel Core**, or
   `http://<your-ha-address>:8123/nspanel_core/`.

## First run: the manager settings

The first page you'll see asks for the **Panel MQTT broker** — the broker
the panels themselves connect to:

- **Broker address / port** — your MQTT broker's address
- **Broker user / password** — the credentials the panels will use (create
  a dedicated one, or leave empty for an anonymous broker)

Save. The manager now listens for panels.

## Rooms

Panels belong to a **room** (the Settings page → Rooms). The first room is
created automatically. Rename it, add more, and delete what you don't
need — deleting a room moves its panels to the first remaining room.
