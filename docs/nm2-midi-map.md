# NM2 MIDI map

Measured over USB with `aseqdump` on 2026-10-23 (logs in `logs/`).
Web-app settings at the time: A minor scale, root A4.
Button numbers refer to `docs/nm2-labeled.png` (left to right, top to bottom).

All messages are on MIDI channel 1.

## Buttons

Press sends Note on (velocity 100), release sends Note off (velocity 0).
A hold is detectable: button 1 held 2.31 s gave Note on at 10:24:26.102, Note off at 10:24:28.413.

| Row | Buttons → notes |
|---|---|
| 1 | 1=69 A4 · 2=71 B4 · 3=72 C5 · 4=74 D5 · 5=76 E5 · 6=77 F5 |
| 2 | 7=79 G5 · 8=81 A5 · 9=83 B5 · 10=84 C6 · 11=86 D6 · 12=88 E6 |
| 3 | 13=89 F6 · 14=91 G6 · 15=93 A6 · 16=95 B6 · 17=96 C7 · 18=98 D7 |

Notes follow the web-app scale: changing scale or root moves them.

## Encoders

| Control | Message | Range |
|---|---|---|
| E1 (left) | CC 1 | 0–127 |
| E2 (right) | CC 2 | 0–127 |

- Absolute values, step of 1 per message; clockwise counts up (assuming the test turned clockwise first).
- Wraps around both ways: 127 → 0 and 0 → 127. On a synth this jumps the parameter from max to min.
- Up to ~100 messages/s when turned fast.
- Contact bounce: at some positions the value flips back and forth by 1 within 2–3 ms
  (e.g. 87, 88, 87, 88, 87, 88 at 10:32:15.24), plus a few repeated identical values.

## Tilt

| Axis | Message | Flat | Range seen |
|---|---|---|---|
| Roll (left/right) | CC 74 | 59–60 | 0–127 |
| Pitch (forward/back) | CC 75 | 62–65 | 0–127 |

360° roll to the right (10:34:57–10:35:09): CC 74 went 60 → 0, held at 0, went silent ~1.75 s,
came back at 24, rose to 127, held at 127, then 103 → 60 back flat.
- The value saturates (0 or 127) well before 90°, so the usable range is a fairly small tilt.
- It does not identify the angle over a full turn: values repeat (e.g. ~60 flat and again mid-turn).
- When the value is stuck at 0 or 127 nothing is sent (sent only on change).
- CC 75 moved only ±5–10 during the roll (cross-talk).

Forward/back tilt (10:42:34–10:42:38): CC 75 went to 127 (forward, assuming forward first),
then 0 (back), then ~65 flat. CC 74 stayed 60–65 except a brief 83–84 while returning.
Both axes behave the same way: saturate quickly, sent only on change.
- Hand jiggle while moving: ±3–15 noise around the trend (e.g. 48 49 42 42 42 45 48 39 33 37 51 39 32),
  plus single-message spikes (88 → 104 → 88). ~75 messages/s total for both axes.

- Sent only when the value changes; completely silent when the NM2 is still.
- Up to ~50 messages/s per axis (20 ms spacing) while moving.
- Very sensitive to vibration: desk taps and button presses cause one-message spikes
  that return on the next message (e.g. 59 → 37 → 59). CC 74 reacts more than CC 75.
  During the 18-button sequence: CC 74 ranged 42–93 with 17 spikes ≥ 8, CC 75 57–73 with 6.
  The box needs a spike filter plus light smoothing.

## Other

Nothing else seen: no clock, sysex, program change, or idle traffic.
