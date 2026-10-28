# Open issue: first tilt jumps to the box's starting value

Found 2026-10-23 while testing `tools/box/nm2_box.py` with Surge XT (pitch axis). Not fixed yet.

## What happens

Some Surge macros are not at the value the box expects. The first time you hold such a
button and tilt, the macro jumps from its own value to the box's value ± the tilt. After that
first move the box and the synth agree, and later presses on that button do not jump.

## Why

The ratchet math is already relative: while held, the box adds the tilt change to the value at press
(`value at press + (tilt now − tilt at press)`). Tilting from 50 to 62 means "+12".

The problem is how MIDI sends it. A normal CC carries an **absolute** number: "set this to 76",
never "add 12". So the box has to turn "+12" into a number, and to do that it needs the current value.
It doesn't know the synth's value, so it uses its own guess: every button starts at 64
(`START` in `tools/box/nm2_box.py`). If the synth's value is 0, "+12" goes out as 76 → jump.

In short, the box remembers each value itself. It never learns the synth's value, so the first move
shows any difference between the two.

## Possible fixes (none chosen yet)

1. **Relative CC mode on the synth.** Some synths can treat a CC as "+n / −n" (relative encoder mode,
   e.g. 65 = +1, 63 = −1). The box would then send only the change, which is what was expected here.
   Works only if the synth supports it for that parameter; check each synth's manual
   (Hydrasynth, MiniFreak, Wavestate, Digitone II, Cobalt8) and Surge.
2. **Read the synth's values.** Computer: ask Surge over OSC at start-up. Hardware: only if the synth
   sends CCs when its own knobs move or a patch loads (needs a second MIDI input on the box).
3. **Box sets the synth at start.** Send all 18 starting values once at power-on, before playing.
   Works everywhere, but overwrites those 18 settings in the patch.
4. **Starting values per preset.** Store a starting value per button to match the patch
   (ties in with the planned "synth presets" feature). Manual to keep in sync.
5. **Start at 0 instead of 64.** Quick fix for settings that really are at 0 (Surge macros);
   other settings still jump.
