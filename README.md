# NM2 hold + tilt ratchet

> **NM2 developer:** start at [`handoff/README.md`](handoff/README.md). The rest of this page is the owner's tools.

A new way to play the **NM2 MIDI controller** (this.is.NOISE inc.): **hold a button and tilt** to change a synth parameter.

- Each of the 18 buttons selects one synth parameter (one MIDI CC).
- While a button is held, tilting moves that parameter up or down from where it was.
- When you let go, the value stays where you left it. The next press picks up from that value, whatever angle the NM2 is at.
  ([Why, and how the code does it](docs/no-jump.md))

The behavior was measured on a real NM2 and validated by hand in the simulator.

> **Warning:** button notes depend on the scale set in the NM2 web app. The box expects **A minor, root A4**.
> Changing the scale or root breaks button detection until `NOTES` in `tools/box/nm2_box.py` is updated.


## Quick start

| I want to… | Run |
|---|---|
| Play with the box (terminal) | `python3 tools/box/nm2_box.py` then pick "NM2 Ratchet" as the synth's MIDI input |
| Play with the box (window) | `python3 tools/box/nm2_gui.py`, or `NM2 Ratchet.exe` on Windows ([setup](docs/windows-setup.md)) |
| Check nothing is broken | `python3 tools/box/test_box.py` (no hardware needed; prints PASS) |
| See the NM2's raw MIDI live (Linux) | `python3 tools/viewer/nm2_live.py` then open http://localhost:8765 |
| Try the behavior in the simulator (Linux, needs the NM2) | same as above, then open http://localhost:8765/sim |

## What each file is

**The box: the program you play with** (`tools/box/`)

| File | What it is |
|---|---|
| `tools/box/nm2_box.py` | **The brain.** Ratchet logic: note → button, tilt → CC value. Runs in the terminal. |
| `tools/box/nm2_gui.py` | The same box in a window: settings + a table of the 18 buttons' CCs. |
| `tools/box/nm2_midi.py` | MIDI connections for Linux (ALSA) and Windows (loopMIDI). Used by the two files above; not run directly. |
| `tools/box/test_box.py` | Automatic test of the box with a fake NM2. Run it after any change. |
| `.github/workflows/windows-exe.yml` | Builds `NM2 Ratchet.exe` on GitHub after every push that changes `tools/`. |

**Measuring and trying ideas: how the behavior was designed** (`tools/viewer/`)

| File | What it is |
|---|---|
| `tools/viewer/nm2_live.py` + `nm2_live.html` | Live viewer of the NM2's MIDI in the browser. Used to measure the tilt. |
| `tools/viewer/nm2_sim.html` | Box + virtual synth simulator, where the ratchet was validated (served at `/sim`). |
| `logs/` | Raw MIDI recordings (NM2 over USB). |

**Documents**

| File | What it is |
|---|---|
| `docs/nm2-midi-map.md` | Everything the NM2 sends: button notes, encoders, tilt, noise. |
| `docs/no-jump.md` | Why the value never jumps on press, and where the code does it. |
| `docs/first-tilt-jump.md` | Open issue: the first tilt can jump when the synth's value differs from the box's. |
| `docs/windows-setup.md` | Running the box on Windows. |
| `docs/nm2-labeled.png` / `.svg`, `nm2_label.jpeg` | NM2 picture with button numbers, and the original photo. |
| `handoff/` | Package for the NM2 developer: spec + portable C code + tests. |

## Status

- Computer box: working on Linux and Windows.
- Hand-off to the NM2 developer: ready in `handoff/`. Make the zip with
  `git archive --format=zip -o nm2-handoff.zip handoff-package` (no git history).
