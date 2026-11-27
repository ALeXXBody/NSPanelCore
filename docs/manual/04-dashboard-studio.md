# 4. The Dashboard studio

The **Dashboard** page is the design studio: the live preview, the page
editor and the Send button.

![The Dashboard studio](https://raw.githubusercontent.com/wiki/ALeXXBody/NSPanelCore/studio-preview.png)

![The full studio](https://raw.githubusercontent.com/wiki/ALeXXBody/NSPanelCore/studio-full.png)

## The three-step flow

1. **Choose a panel** — the selector at the top
2. **Build pages** — the tabs below the preview
3. **Send to panel** — compile + deliver to the glass

## Build the screensaver tab

- The **photo** shown on the screensaver: pick one of your dashboard pages
  as the screensaver source — its photo (uploaded on that page) becomes
  the screensaver background
- The clock/date **style**: the font, the weight, the color, the
  alignment
- The **activation timeout**: seconds of no touch before the panel
  returns to the screensaver (0 = never sleep)

## Build the dashboard tab

- **Pages**: add, rename, delete; each page carries a title and an
  optional photo background (uploaded per page — the photo is processed
  into a darkened dashboard variant and a full-brightness screensaver
  variant)
- **Items**: click an empty slot in the preview, pick a Home Assistant
  entity (the searchable library), set the label. The widget type follows
  the entity's domain (light, switch, scene, sensor, climate)
- **Send to panel**: compiles your design into a display image and
  delivers it over the air — the panel confirms with its own boot
  announcement; a failed delivery is retried automatically and can never
  be recorded as "delivered" unless the display actually booted it

## What you see is what the panel renders

The preview is pixel-faithful: the same cards, the same labels, the same
state squares (grey = off, cyan = on). Tapping a light tile on the glass
opens its detail card on the panel (on/off, brightness −/+, the color
presets).

## The delivery's safety rails

- The delivery is **not "done" until the display announces a valid boot**
  — a partial image can never be recorded as delivered
- If the image fails, the panel power-cycles the display and **re-delivers
  automatically** (up to twice per boot)
- The panel reports the delivered image's checksum at every check-in; the
  manager re-delivers automatically if it ever drifts
