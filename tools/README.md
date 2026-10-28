# tools/

Two separate groups. Neither uses the other.

## `box/`: the computer box (the program you play with)

```
nm2_gui.py ──▶ nm2_box.py ──▶ nm2_midi.py
 (window)      (the ratchet)   (MIDI in/out, Linux + Windows)
```

| File | What it is |
|---|---|
| `nm2_box.py` | **The brain.** Ratchet logic: note → button, tilt → CC value. Runs on its own in the terminal. |
| `nm2_gui.py` | The same box in a window. Uses `nm2_box.py` for the logic; adds settings and a CC table. |
| `nm2_midi.py` | MIDI connections. Used by the two files above; not run directly. |
| `test_box.py` | Automatic test of `nm2_box.py` with a fake NM2. Also used by `nm2_gui.py --selftest`. |

`../handoff/make_vectors.py` also uses `nm2_box.py`: the C tests are checked against it.

## `viewer/`: measuring and the simulator

| File | What it is |
|---|---|
| `nm2_live.py` | Small web server: reads the NM2's MIDI (Linux, `aseqdump`) and serves the two pages below. |
| `nm2_live.html` | Live view of the raw MIDI at http://localhost:8765. |
| `nm2_sim.html` | Box + virtual synth simulator at http://localhost:8765/sim, where the behavior was validated. |
