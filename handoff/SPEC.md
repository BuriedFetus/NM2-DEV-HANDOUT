# Hold + tilt ratchet: behavior spec

Version 1, 2026-10-24. Reference code: `ratchet/` (C99). Validated by the NM2 owner in the simulator (`../tools/viewer/nm2_sim.html`); also running as a computer box
(`../tools/box/nm2_box.py`) between a real NM2 and Surge XT.

## In one paragraph

The 18 buttons stop playing notes and become **parameter selectors**. While a button is held,
tilting the NM2 moves that button's CC **relative to its last value**: tilt forward 10 steps, the CC goes up 10.
On release the CC keeps its value. The next press continues from there, whatever angle the hand is at:
the CC never jumps to match the hand. To get more range, release, level the NM2, and press again,
like a ratchet wrench.

## Inputs

| Input | What the module needs |
|---|---|
| Button press / release | Button index 0–17 (physical buttons, not notes). |
| Tilt | Per axis, the same 0–127 value the NM2 sends today as CC 74 (roll) / CC 75 (pitch). |
| Time | A millisecond counter (wrap-around is fine). |

**Tilt feed rate:** the filter was tuned on the NM2's MIDI stream, about 50 readings/s per axis (20 ms) while moving.
Feed it readings at a steady ~50 Hz, **including unchanged values**. The MIDI stream only sends changes,
so a still hand used to leave the average stuck a little behind. Feeding unchanged values fixes that.

The replay tests (`ratchet/test_ratchet.c`, `vectors/`) and the Python box feed **only the changes**, as
they arrive over MIDI, because that is all a recording contains. So on the NM2, steady feeding will give
slightly different output from the vectors; that is expected and better. To check a port against the
vectors, feed it changes only, like the test does.

## Rules

1. **Hold.** A press selects that button. A press while another button is held takes over. Releasing the
   selected button ends the hold; releasing any other button does nothing.
2. **Silent press and release.** Nothing is ever sent on press or release, only when the tilt moves.
   This is an ear-safety rule: a press must never make the sound jump.
3. **Settle, then reference.** The press itself shakes the NM2 (measured single-reading spikes, e.g. 59 → 37 → 59). The reference is
   taken at the first update at least `settle_ms` (40 ms) after the press: the current filtered tilt becomes
   the *reference*, and the button's current CC value becomes the *start*.
4. **Ratchet.** While held: `target = clamp(start + (tilt − reference) × gain, 0, 127)`, rounded to nearest.
5. **Slew limit.** The sent value moves toward the target by at most `slew` values per second
   (300/s → 3 per 10 ms tick, at least 1 per tick). It keeps moving after release until it reaches the target.
6. **Send only changes.** A CC goes out only when its value changes, on a 10 ms tick.
7. **Memory per button.** Each button (and each axis, if a button uses both) keeps its own value.
   At power-on all values are `start_value` (64). Nothing is sent at power-on (see Open decisions).
8. **Filter.** Each tilt reading goes through a median of the last 3 (removes one-reading spikes from taps
   and presses), then a moving average of the last 7 medians (hand jiggle).
9. **Direction.** Tilting forward raises the value (pitch). For roll, tilting right raises the value; the raw
   CC 74 goes *down* when tilting right, so roll is inverted (`127 − tilt`).
10. **What goes out in this mode.** The resulting CCs only. Button notes and raw tilt CCs 74/75 are not sent.
    Encoders (CC 1/2) work as today.

The reference code chooses ties-to-even rounding only so it matches the Python tools exactly.
Any rounding to nearest is fine on the NM2.

## Settings and defaults

| Setting | Default | Why |
|---|---|---|
| CC per button and axis | pitch only, buttons 1–18 → CC 102–119 | Placeholder (undefined CCs); in practice set per synth. |
| MIDI channel | 1 | |
| Start value | 64 | Middle; see the first-tilt jump below. |
| Spike filter | median of 3, on | Button presses and desk taps cause single-reading spikes. |
| Smoothing | average of 7 | Picked by the owner in the live viewer: steady without feeling slow. |
| Settle | 40 ms | The press jolt settles in about 30–50 ms. |
| Slew | 300 values/s | Full range in about 0.4 s; stops any sudden step. |
| Gain | 1 (100 %) | One CC step per tilt step: the setting the owner validated. |

## What was measured on the NM2

Full details: [`../docs/nm2-midi-map.md`](../docs/nm2-midi-map.md). Raw logs: `../logs/`.

- Buttons send Note on (velocity 100) at press and Note off at release, so holds are detectable.
- Tilt: roll = CC 74 (flat ≈ 60), pitch = CC 75 (flat ≈ 63), channel 1. Both saturate at 0/127 well before 90°.
- Sent only on change, up to ~50 messages/s per axis; silent when still.
- Noise: ±3–15 while the hand moves, single-reading spikes from taps and presses (e.g. 59 → 37 → 59).
  Roll is more sensitive than pitch.
- Over Bluetooth, tilt values are sometimes repeated and messages arrive in bursts (half within 2 ms).
- **Button notes depend on the scale.** All measurements, logs and test recordings were made with the web
  app set to **A minor, root A4** (buttons 1–18 = notes 69, 71, 72 … 98). The computer box finds buttons by
  these notes, so it breaks if the scale or root changes. In the firmware this problem doesn't exist: pass the
  physical button number (0–17) to `ratchet_button()`, never the note, and the mode works with any scale.

## Firmware notes

- **Cost:** about 190 bytes of RAM (`sizeof(ratchet)`, config included) and about 1.4 KB of code.
  Integer math only, no floats, no malloc. The arithmetic is written to be safe on 8/16-bit `int`.
- **Hooking it up** (pseudo code):

  ```c
  ratchet R;  ratchet_config cfg;
  ratchet_default_config(&cfg);            /* then set CCs / channel from the web-app settings */
  ratchet_init(&R, &cfg, millis());

  on_button(i, down)        -> ratchet_button(&R, i, down, millis());   /* instead of sending the note */
  every 20 ms (tilt read)   -> ratchet_tilt(&R, RATCHET_ROLL, roll_0_127, millis());
                               ratchet_tilt(&R, RATCHET_PITCH, pitch_0_127, millis());
  every 10 ms               -> ratchet_tick(&R, millis(), send_cc, NULL);  /* send_cc: USB + BLE */
  ```
- **Higher tilt resolution:** if the sensor gives more than 7 bits, the module can be widened, but gain 1
  should still mean "the current 0–127 tilt range = the full CC range": that feel is what was validated.

## Open decisions (for the developer and the owner)

1. **Turning the mode on.** A web-app setting? For all buttons, or per button (some play notes, some select)?
2. **CC per button.** The owner plays 5 synths (Hydrasynth, MiniFreak, Wavestate, Digitone II, Cobalt8).
   Ideally the web app sets the CC (and axis) per button, maybe as presets per synth.
3. **First-tilt jump.** The NM2 doesn't know the synth's real values, so the first tilt on a button can jump
   from the synth's value to `64 ± tilt`. Options: send all start values at power-on, store start values per
   preset, or relative CCs on synths that support them. Details: [`../docs/first-tilt-jump.md`](../docs/first-tilt-jump.md).
4. **Keeping values across power cycles.** Store the 18 values in flash on power-off, or always start at 64?
5. **Both axes per button.** The module supports it (two CCs per button); is it wanted in the UI?
6. **Feedback.** A LED showing the held button, or a hint when the value hits 0 or 127?
