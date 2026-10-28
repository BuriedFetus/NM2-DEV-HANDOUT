#!/usr/bin/env python3
"""NM2 box on the computer: the hold + tilt ratchet as a virtual MIDI port.

Reads the NM2 (Bluetooth or USB), runs the same logic as the simulator (tools/viewer/nm2_sim.html)
and sends the result out of a MIDI port "NM2 Ratchet".
Point the synth or DAW at "NM2 Ratchet", never at the NM2 itself.
Works on Linux and Windows (Windows setup: docs/windows-setup.md). Window version: tools/box/nm2_gui.py.

- NM2 notes are never forwarded. Raw tilt (CC 74/75) is never forwarded.
- Other messages (encoders CC 1/2) pass through.
- While a button is held, tilt changes that button's CC relative to its value at press.
  No CC is sent on press or release.

Run:  python3 tools/box/nm2_box.py              (Ctrl+C to stop; on Windows: py tools\\box\\nm2_box.py)
      python3 tools/box/nm2_box.py --axis roll
"""

import argparse
import threading
import time
from dataclasses import dataclass, field

from nm2_midi import DEFAULT, MidiSetupError, open_midi

# Button notes as measured (docs/nm2-midi-map.md): A minor from 69, buttons 1–18.
NOTES = [69, 71, 72, 74, 76, 77, 79, 81, 83, 84, 86, 88, 89, 91, 93, 95, 96, 98]
BUTTON_OF_NOTE = {n: i for i, n in enumerate(NOTES)}
TILT_CCS = (74, 75)

# Surge XT preset: (CC, name) per button. Buttons 1–8 use Surge's default macro CCs (41–48);
# buttons 9–18 use CCs 20–29, meant for Surge's scene A parameters (filter, envelope, LFO).
SURGE = [
    (41, "Macro 1"), (42, "Macro 2"), (43, "Macro 3"), (44, "Macro 4"),
    (45, "Macro 5"), (46, "Macro 6"), (47, "Macro 7"), (48, "Macro 8"),
    (20, "Filter 1 cutoff"), (21, "Filter 1 resonance"), (22, "Filter 1 env amount"),
    (23, "Filter 2 cutoff"), (24, "Filter 2 resonance"), (25, "Filter balance"),
    (26, "Waveshaper drive"), (27, "Filter EG decay"), (28, "Amp EG release"), (29, "LFO 1 rate"),
]

# Defaults (the window can change them while playing)
OUT_CHANNEL = 0          # MIDI channel 1
START = 64               # each button's CC value at start (power-on)
SMOOTH = 7               # moving average length
SETTLE = 0.040           # s after press before the reference is taken
SLEW = 300               # max values/s
GAIN = 1
TICK = 0.010             # s between output steps

NOTE_OFF, NOTE_ON, AFTERTOUCH, CONTROL = 0x80, 0x90, 0xA0, 0xB0


@dataclass
class Settings:
    axis: str = "pitch"          # "pitch" (back/forward) or "roll" (left/right)
    spike: bool = True           # median of 3 removes one-message spikes
    smooth: int = SMOOTH
    settle: float = SETTLE
    slew: float = SLEW
    gain: float = GAIN
    start: int = START
    channel: int = OUT_CHANNEL
    buttons: list = field(default_factory=lambda: [[cc, name] for cc, name in SURGE])  # [CC, name] per button


# --- The ratchet (same as tools/viewer/nm2_sim.html) ---

class Box:
    """report(event, *args) is called with:
    ("press", button, value), ("release", button, value), ("value", button, value),
    ("connected", via, port), ("cannot", port), ("gone", via), ("waiting",), ("error", text)."""

    def __init__(self, midi, settings, report):
        self.midi, self.s, self.report = midi, settings, report
        self.lock = threading.Lock()  # the window may reset values while the loop runs
        self.hist = {cc: [] for cc in TILT_CCS}
        self.avg = {cc: [] for cc in TILT_CCS}
        self.f = {cc: None for cc in TILT_CCS}
        self.box = [settings.start] * 18      # what the box believes the synth has
        self.out = [settings.start] * 18      # output value, moving toward target under the speed limit
        self.target = [settings.start] * 18
        self.selected = None
        self.press_at = 0
        self.ref = None
        self.ref_axis = None
        self.start_val = None
        self.last_tick = time.monotonic()

    def tilt(self):
        # Tilting right lowers CC 74, so roll is inverted: right adds. Forward raises CC 75.
        if self.s.axis == "pitch":
            return self.f[75]
        return None if self.f[74] is None else 127 - self.f[74]

    def filter(self, cc, v):
        h = self.hist[cc]
        h.append(v)
        del h[:-3]
        m = sorted(h)[1] if self.s.spike and len(h) == 3 else v
        a = self.avg[cc]
        a.append(m)
        del a[:-max(1, self.s.smooth)]
        self.f[cc] = sum(a) / len(a)

    def on_message(self, msg):
        kind = msg[0] & 0xF0
        if kind in (NOTE_OFF, NOTE_ON, AFTERTOUCH):
            if kind == AFTERTOUCH:
                return
            b = BUTTON_OF_NOTE.get(msg[1])
            if b is None:
                return
            if kind == NOTE_ON and msg[2] > 0:
                self.selected, self.press_at, self.ref = b, time.monotonic(), None
                self.report("press", b, self.box[b])
            elif self.selected == b:
                self.selected = self.ref = None
                self.report("release", b, self.box[b])
        elif kind == CONTROL and msg[1] in TILT_CCS:
            self.filter(msg[1], msg[2])
        elif CONTROL <= msg[0] < 0xF0:   # channel messages other than notes (CC, program, pressure, bend…)
            self.midi.send(msg)

    def update(self):
        b = self.selected
        if b is None or time.monotonic() - self.press_at < self.s.settle:
            return
        t = self.tilt()
        if t is None:
            return
        if self.ref is None or self.ref_axis != self.s.axis:  # axis changed while held: new reference, no jump
            self.ref, self.ref_axis, self.start_val = t, self.s.axis, self.box[b]
            return
        self.target[b] = max(0, min(127, round(self.start_val + (t - self.ref) * self.s.gain)))

    def tick(self):
        now = time.monotonic()
        max_step = max(1, self.s.slew * (now - self.last_tick))
        self.last_tick = now
        for k in range(18):
            if self.target[k] == self.out[k]:
                continue
            step = max(-max_step, min(max_step, self.target[k] - self.out[k]))
            self.out[k] = self.box[k] = round(self.out[k] + step)
            self.midi.send([CONTROL | self.s.channel, self.s.buttons[k][0], self.out[k]])
            self.report("value", k, self.out[k])

    def reset_values(self):
        """Forget what the synth has: every button back to the start value. Sends nothing."""
        with self.lock:
            self.box = [self.s.start] * 18
            self.out = [self.s.start] * 18
            self.target = [self.s.start] * 18
            if self.selected is not None:
                self.ref = None   # re-reference from the new value, no jump


# --- Following the NM2 as it connects and disconnects ---

class PortWatcher(threading.Thread):
    """Picks the NM2 port to read: Bluetooth if present (like the real box), else USB."""

    def __init__(self, list_ports, prefer, stop):
        super().__init__(daemon=True)
        self.list_ports, self.prefer, self.stop = list_ports, prefer, stop
        self.wanted, self.lock = None, threading.Lock()

    def run(self):
        while not self.stop.is_set():
            ports = self.list_ports()
            pick = next((p for p, via in ports.items() if via == self.prefer), next(iter(ports), None))
            with self.lock:
                self.wanted = (pick, ports.get(pick)) if pick else None
            self.stop.wait(2)


def run(midi, box, prefer, stop):
    """The box's main loop, until stop is set."""
    watcher = PortWatcher(midi.ports, prefer, stop)
    watcher.start()
    connected = None
    next_tick = time.monotonic()
    while not stop.is_set():
        with watcher.lock:
            wanted = watcher.wanted
        if wanted != connected:
            if connected:
                midi.disconnect(connected[0])
                box.report("gone", connected[1])
            if wanted:
                if midi.connect(wanted[0]):
                    box.report("connected", wanted[1], wanted[0])
                else:
                    box.report("cannot", wanted[0])
            else:
                box.report("waiting")
            connected = wanted
            box.selected = box.ref = None  # a reconnect may lose a note off

        msgs = midi.wait(max(0, next_tick - time.monotonic()))
        with box.lock:
            for msg in msgs:
                box.on_message(msg)
            box.update()
            if time.monotonic() >= next_tick:
                box.tick()
                next_tick = max(next_tick + TICK, time.monotonic())
    if connected:
        midi.disconnect(connected[0])


def console(settings):
    """report() for the command line: prints what the box does."""
    def report(event, *a):
        if event == "press":
            b, v = a
            cc, name = settings.buttons[b]
            print(f"\nbutton {b + 1}: {name} (CC {cc}) = {v}", flush=True)
        elif event == "release":
            print(f"\nreleased at {a[1]}", flush=True)
        elif event == "value":
            b, v = a
            if b == report.box.selected:
                print(f"\r  {settings.buttons[b][1]} = {v:3d}   ", end="", flush=True)
        elif event == "connected":
            print(f"\nReading NM2 over {a[0]} ({a[1]})", flush=True)
        elif event == "cannot":
            print(f"\nCannot connect to {a[0]}", flush=True)
        elif event == "gone":
            print(f"\nNM2 {a[0]} gone", flush=True)
        elif event == "waiting":
            print("\nWaiting for the NM2…", flush=True)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--axis", choices=["roll", "pitch"], default="pitch", help="tilt axis (default pitch)")
    ap.add_argument("--prefer", choices=["Bluetooth", "USB"], default="Bluetooth",
                    help="NM2 connection to read when both are present (default Bluetooth)")
    ap.add_argument("--midi", choices=["alsa", "rtmidi"], default=DEFAULT,
                    help=f"MIDI system: alsa (Linux) or rtmidi (Windows; needs python-rtmidi). Default {DEFAULT}")
    args = ap.parse_args()

    try:
        midi = open_midi(args.midi, "NM2 Ratchet")
    except MidiSetupError as e:
        raise SystemExit(str(e))
    settings = Settings(axis=args.axis)
    report = console(settings)
    box = report.box = Box(midi, settings, report)
    print(f"NM2 Ratchet ready on {midi.where} (axis: {args.axis}). "
          "Select 'NM2 Ratchet' as the synth's MIDI input. Ctrl+C to stop.", flush=True)
    run(midi, box, args.prefer, threading.Event())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
