# 2. Accept a panel

A panel that joins your network appears on the **NSPanels** page in one of
two states: *discovered* (a card asking to be accepted) or *awaiting
accept*.

![The NSPanels page](https://raw.githubusercontent.com/wiki/ALeXXBody/NSPanelCore/nspanels.png)

## Accept

Press **Accept** on the panel's card. The manager:

1. Sends the panel its broker credentials over HTTP (the panel reboots
   into MQTT mode)
2. Publishes the device config — the button modes, the relay boot
   defaults — and re-asserts it at **every register**, so the panel always
   matches what you've configured here
3. Evaluates the firmware/display updates and offers them

## The panel's identity

- **The name** is what you see in the manager — rename freely from the
  panel's edit page.
- **The hostname** (the wire name) is what the panel reports. The commands
  follow the *hostname*, so renames never black-hole the commands.

## Deny / delete / allow again

- **Deny** — the panel keeps running but is ignored by the manager
- **Delete** — removes the row AND remembers the MAC (a deleted panel
  re-registers instantly otherwise); "Allow again" on the Denied tab
  clears it

## The physical buttons and the relays

The panel's two front switches and its two built-in relays are configured
on the panel's **Panel hardware** tab (in the Dashboard studio):

- **Button mode** — per switch:
  - *Direct*: the press toggles its own relay on the panel
  - *Detached*: the press is reported to the manager, which routes it to
    any Home Assistant entity you bind (not necessarily the relay)
  - *Custom MQTT*: the press publishes to your own topic/payload
  - *Follow*: the relay toggles AND the press is reported
- **Relay boot state** — "always on" boots the relay closed at every
  power-up (useful when the relay powers other devices' circuit)
- **Relay 1/2 registered as** — Switch or Light: this decides which Home
  Assistant platform represents the relay
- **Show relay buttons on the home page** — whether the delivered
  dashboard's home page carries the two relay tiles

The panel **always re-syncs this configuration from the manager** — every
change in the studio reaches the panel at its next check-in.
