# 5. The screensaver

The screensaver is what the panel shows when idle: your photo, the clock,
the date, and the weather.

## The photo

Set on the **Build the dashboard** tab: pick the page whose photo becomes
the screensaver background. The photo is processed into two variants —
the full-brightness one for the screensaver and a darkened one behind the
dashboard's tiles.

## The clock and date

The font, weight, color and alignment are styled on the **Build the
screensaver** tab; the preview updates live.

## The weather

The weather block sits at the bottom of the screensaver:

- The **condition icon** (sun / cloud / rain / snow — chosen from the
  actual forecast code)
- The **outside temperature** (large) — from your weather provider, or
  the per-panel entity override
- The **room temperature** — from the panel's own sensor or a bound HA
  sensor
- The **forecast rows** — the day name and the max/min temps for the next
  days

Toggle what you want on the Screensaver tab; the panel receives the
payload immediately (it replays at every check-in too).

## The clock shows the real time immediately

When the panel returns to the screensaver (after the idle timeout), the
clock shows the current time from the first frame — the panel stores the
last received time and writes it the moment the page opens.

## The wake

Any touch wakes the panel to the dashboard. After the configured idle
timeout with no touch, the screensaver returns automatically.
