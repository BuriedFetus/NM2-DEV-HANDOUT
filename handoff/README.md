# Hand-off: hold + tilt ratchet for the NM2 firmware

For the NM2 developer. This folder has what you need to build the "hold a button + tilt" feature
into the NM2 itself.

## Start here

1. **[SPEC.md](SPEC.md):** the behavior in 10 rules, the settings, what was measured on the NM2, and open decisions.
2. **Run the tests** (any computer with a C compiler, nothing to plug in): see "The code" below.
3. **[ratchet/](ratchet/):** the reference implementation, ready to drop in.
4. **Optional, try it by hand:** the simulator `../tools/viewer/nm2_sim.html` shows the box and a virtual synth,
   driven by a real NM2. It needs **Linux**, `aseqdump` (package `alsa-utils`), Python 3, and an NM2 on USB
   or Bluetooth (A minor, root A4 in the web app, so the button notes match).
   Run `python3 ../tools/viewer/nm2_live.py`, then open http://localhost:8765/sim.
   It has no on-screen tilt or buttons, so it does nothing without an NM2.

## The code

| File | What it is |
|---|---|
| `ratchet/ratchet.h` | The API: `ratchet_button()`, `ratchet_tilt()`, `ratchet_tick()` (every 10 ms), and the config. |
| `ratchet/ratchet.c` | The implementation: ~165 lines of C99, integer only, ~190 bytes of RAM, no dependencies. |
| `ratchet/test_ratchet.c` | Tests: one per rule in the spec, plus a replay of a real NM2 recording. |
| `vectors/` | Expected output for that replay, made by the validated Python box. |
| `make_vectors.py` | Remakes `vectors/` from the Python box (`../tools/box/nm2_box.py`). |

Run the tests (any machine with a C compiler). Keep the folders as they are in the zip:
the replay reads `../../logs/`.

```
cd handoff/ratchet
make test          # prints "ok" per check, then PASS
```

The replay feeds 80 minutes of real NM2 recording (`../logs/nm2-usb-2026-10-23-timed.txt`: tilting, jiggle,
spikes, button holds) through the C module and checks every CC it sends against the Python box:
same time, same CC, same value. Today: 1,066 CCs on the pitch axis and 1,125 on roll, all identical.

If you port the module to your codebase, run the same replay against your version.
The replay rules are in the top comment of `make_vectors.py`.

## Notes

- The module takes **button numbers**, not notes. The box outside the NM2 has to find buttons by their
  note number. That breaks if the scale changes, so don't copy it into the firmware.
- Compiled and tested with gcc on Linux (x86-64). Not yet compiled for an 8/16-bit chip: the arithmetic was
  checked by hand for 16-bit `int`.
- Questions: ask the owner (the person who sent you this package). The rest of the repo (`../README.md`) has the measuring tools and the computer box.
