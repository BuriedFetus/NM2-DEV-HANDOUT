# Running the box on Windows

`tools/box/nm2_box.py` runs the hold + tilt ratchet on Windows the same way it does on Linux.
Use it to play Windows-only synths (Korg Wavestate Native, Arturia Analog Lab…) with the NM2.

```
NM2 ─USB─▶ NM2 Ratchet app ─▶ "NM2 Ratchet" (loopMIDI port) ─▶ synth plugin
```

## Easy way: the app (no Python needed)

GitHub builds **NM2 Ratchet.exe** automatically after every change to `tools/` (`.github/workflows/windows-exe.yml`).

1. **Install loopMIDI** from https://www.tobias-erichsen.de/software/loopmidi.html. Open it, type
   `NM2 Ratchet` in the "New port-name" box (exactly like that), and click **+**. Keep it running (tray icon).
2. **Download the app.** On github.com (logged in), open the private repo `nm2-firmware` → **Actions** tab →
   click the latest green **Windows exe** run → at the bottom, under *Artifacts*, click **NM2-Ratchet-windows**.
   Unzip it; inside is `NM2 Ratchet.exe`. Put it anywhere (Desktop is fine). Downloads are kept 30 days.
3. **Start it.** The first time, Windows shows "Windows protected your PC" because the app isn't signed:
   click **More info → Run anyway**. Windows remembers this.
4. Plug in the NM2 with the USB cable. The window should say **NM2: connected over USB**.
5. In the synth: enable **NM2 Ratchet** as MIDI input, and make sure the **NM2 itself is not enabled**.
6. Hold a button and tilt. The button's row shows **◀ held** and its value moves.

In the window:
- **Settings** (left) apply immediately: tilt axis, spike filter, jiggle smoothing, gain, speed limit,
  settle time, MIDI channel, starting value.
- **Buttons** (right): type the CC number each button should send for your synth, and a name to remember it.
  **Load Surge map** puts back the Surge XT numbers. **Reset values to start** tells the app the synth is back
  at the starting value (it sends nothing).
- Everything is saved in `%APPDATA%\NM2 Ratchet\settings.json` and comes back next time.
- If the window says loopMIDI or "NM2 Ratchet" is missing, fix it in loopMIDI and click **Try again**.

## Alternative: run the Python script

## One-time setup

1. **Get the repo onto the Windows machine.** On github.com (logged in), open the private repo
   `nm2-firmware` → green **Code** button → **Download ZIP**, then unzip it somewhere, e.g. `Documents\nm2-firmware`.
   (Or `git clone` it if Git is installed.)
2. **Install Python** from https://www.python.org/downloads/ (3.10 or newer).
   On the first installer screen, tick **"Add python.exe to PATH"**.
3. **Install the MIDI library.** Open *Command Prompt* (Start → type `cmd`) and run:
   ```
   py -m pip install python-rtmidi
   ```
4. **Install loopMIDI** from https://www.tobias-erichsen.de/software/loopmidi.html.
   Open it, type `NM2 Ratchet` in the "New port-name" box (exactly like that), and click **+**.
   loopMIDI must be running whenever you use the box (it can start with Windows from its tray icon).

## Every time

1. Plug the NM2 in with the USB cable.
2. Make sure loopMIDI is running (tray icon).
3. In Command Prompt:
   ```
   cd Documents\nm2-firmware
   py tools\box\nm2_box.py
   ```
   It should print `NM2 Ratchet ready on port 'NM2 Ratchet …'` and then `Reading NM2 over USB (…)`.
   Options: `py tools\box\nm2_box.py --axis roll` to use left/right tilt instead of back/forward.
4. In the synth (standalone app or DAW): MIDI input settings → enable **NM2 Ratchet**,
   and make sure the **NM2 itself is not enabled**.
5. Hold a button and tilt. Stop the box with **Ctrl+C**.

## If something goes wrong

- **"No MIDI port named 'NM2 Ratchet'"**: loopMIDI isn't running, or the port name is different. Fix it
  in loopMIDI and start the box again.
- **"Cannot connect to …NM2…"**: another program has the NM2 open. On Windows only one program at a time
  can read a MIDI input. Untick the NM2 in the synth/DAW, close other MIDI apps, unplug and replug the NM2.
- **"python-rtmidi is missing"**: run step 3 of the setup again.
- **`py` is not recognized**: Python wasn't added to PATH; rerun the Python installer, choose *Modify*,
  and tick "Add Python to environment variables".
- **Bluetooth:** untested on Windows. If Windows shows the NM2 as a Bluetooth MIDI port, the box uses
  it automatically; otherwise use the cable.
- The live viewer and simulator (`tools/viewer/nm2_live.py`) are Linux-only.
