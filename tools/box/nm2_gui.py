#!/usr/bin/env python3
"""NM2 Ratchet: the box (nm2_box.py) in a window, with its settings and a CC table.

Built into "NM2 Ratchet.exe" for Windows by .github/workflows/windows-exe.yml.
Settings are saved in %APPDATA%\\NM2 Ratchet\\settings.json (Linux: ~/.config/nm2-ratchet/settings.json).

Run:  python tools/box/nm2_gui.py
      python tools/box/nm2_gui.py --selftest   (fake NM2, checks the window, closes; used by the build)
"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict, fields
from pathlib import Path
from tkinter import ttk

from nm2_box import SURGE, Box, Settings, run
from nm2_midi import DEFAULT, MidiSetupError, open_midi

if os.environ.get("APPDATA"):
    SETTINGS_FILE = Path(os.environ["APPDATA"]) / "NM2 Ratchet" / "settings.json"
else:
    SETTINGS_FILE = Path.home() / ".config" / "nm2-ratchet" / "settings.json"

GREEN, RED, GREY = "#1a8f1a", "#c0392b", "#777777"


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text())
        s = Settings(**{f.name: data[f.name] for f in fields(Settings) if f.name in data})
    except (OSError, ValueError, TypeError):
        return Settings()
    if len(s.buttons) != 18:
        s.buttons = Settings().buttons
    return s


def save_settings(s):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(asdict(s), indent=1))


class App:
    def __init__(self, root, settings, make_midi, persist=True):
        self.root, self.s, self.make_midi, self.persist = root, settings, make_midi, persist
        self.events = queue.Queue()   # from the box's thread to the window
        self.box = Box(None, settings, lambda *e: self.events.put(e))
        self.midi = self.worker = self.save_job = None
        self.stop = threading.Event()
        root.title("NM2 Ratchet")
        self.build()
        self.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.poll)

    # --- layout ---

    def build(self):
        top = ttk.Frame(self.root, padding=10)
        top.grid(sticky="nsew")

        status = ttk.Frame(top)
        status.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.nm2_status = tk.Label(status, anchor="w", justify="left")
        self.nm2_status.grid(row=0, column=0, sticky="w")
        self.out_status = tk.Label(status, anchor="w", justify="left", wraplength=700)
        self.out_status.grid(row=1, column=0, sticky="w")
        self.retry = ttk.Button(status, text="Try again", command=self.start)
        self.set_nm2_status("waiting")

        # Settings (left)
        sf = ttk.LabelFrame(top, text="Settings", padding=8)
        sf.grid(row=1, column=0, sticky="nw", padx=(0, 10))
        s = self.s
        row = 0

        ttk.Label(sf, text="Tilt axis").grid(row=row, column=0, sticky="w")
        axis = tk.StringVar(value=s.axis)
        af = ttk.Frame(sf)
        af.grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(af, text="pitch (back/forward)", variable=axis, value="pitch").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(af, text="roll (left/right)", variable=axis, value="roll").grid(row=1, column=0, sticky="w")
        self.watch(axis, lambda v: setattr(s, "axis", v))
        row += 1

        spike = tk.BooleanVar(value=s.spike)
        ttk.Checkbutton(sf, text="Spike filter (ignores single jumps)", variable=spike).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.watch(spike, lambda v: setattr(s, "spike", v))
        row += 1

        def slider(label, value, frm, to, res, apply):
            nonlocal row
            ttk.Label(sf, text=label).grid(row=row, column=0, sticky="sw", pady=(4, 0))
            var = tk.DoubleVar(value=value)
            tk.Scale(sf, variable=var, from_=frm, to=to, resolution=res, orient="horizontal",
                     length=180).grid(row=row, column=1, sticky="w")
            self.watch(var, apply)
            row += 1

        slider("Jiggle smoothing\n(values averaged)", s.smooth, 1, 15, 1, lambda v: setattr(s, "smooth", int(v)))
        slider("Gain\n(value change per tilt)", s.gain, 0.25, 4, 0.25, lambda v: setattr(s, "gain", v))
        slider("Speed limit\n(values per second)", s.slew, 20, 2000, 10, lambda v: setattr(s, "slew", v))
        slider("Settle time after press\n(milliseconds)", s.settle * 1000, 0, 150, 5,
               lambda v: setattr(s, "settle", v / 1000))

        def number(label, value, frm, to, apply):
            nonlocal row
            ttk.Label(sf, text=label).grid(row=row, column=0, sticky="w", pady=(6, 0))
            var = tk.IntVar(value=value)
            tk.Spinbox(sf, textvariable=var, from_=frm, to=to, width=5).grid(row=row, column=1, sticky="w", pady=(6, 0))
            self.watch(var, lambda v: frm <= v <= to and apply(v))
            row += 1

        number("MIDI channel", s.channel + 1, 1, 16, lambda v: setattr(s, "channel", v - 1))
        number("Starting value\n(at start and on Reset)", s.start, 0, 127, lambda v: setattr(s, "start", v))

        # Buttons table (right)
        tf = ttk.LabelFrame(top, text="Buttons: which CC each one changes", padding=8)
        tf.grid(row=1, column=1, sticky="nw")
        for c, h in enumerate(["#", "Name", "CC", "Value"]):
            ttk.Label(tf, text=h).grid(row=0, column=c, sticky="w", padx=3)
        self.rows = []
        for b in range(18):
            cc, name = s.buttons[b]
            name_var, cc_var = tk.StringVar(value=name), tk.IntVar(value=cc)
            ttk.Label(tf, text=str(b + 1), width=3).grid(row=b + 1, column=0)
            ttk.Entry(tf, textvariable=name_var, width=20).grid(row=b + 1, column=1, padx=3, pady=1)
            tk.Spinbox(tf, textvariable=cc_var, from_=0, to=127, width=4).grid(row=b + 1, column=2, padx=3)
            bar = ttk.Progressbar(tf, maximum=127, length=130)
            bar.grid(row=b + 1, column=3, padx=3)
            val = ttk.Label(tf, width=4, anchor="e")
            val.grid(row=b + 1, column=4)
            held = tk.Label(tf, width=7, anchor="w", fg=GREEN)
            held.grid(row=b + 1, column=5)
            self.watch(name_var, lambda v, b=b: self.set_button(b, name=v))
            self.watch(cc_var, lambda v, b=b: 0 <= v <= 127 and self.set_button(b, cc=v))
            self.rows.append((name_var, cc_var, bar, val, held))
            self.show_value(b, self.box.box[b])

        bf = ttk.Frame(tf)
        bf.grid(row=20, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Button(bf, text="Load Surge map", command=self.load_surge).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(bf, text="Reset values to start", command=self.reset_values).grid(row=0, column=1)

    def watch(self, var, apply):
        """Call apply(value) whenever var changes to a valid value, then save."""
        def changed(*_):
            try:
                value = var.get()
            except (tk.TclError, ValueError):   # half-typed number
                return
            apply(value)
            self.schedule_save()
        var.trace_add("write", changed)

    # --- actions ---

    def set_button(self, b, cc=None, name=None):
        old_cc, old_name = self.s.buttons[b]
        self.s.buttons[b] = [old_cc if cc is None else cc, old_name if name is None else name]

    def load_surge(self):
        for (name_var, cc_var, *_), (cc, name) in zip(self.rows, SURGE):
            name_var.set(name)
            cc_var.set(cc)

    def reset_values(self):
        self.box.reset_values()
        for b in range(18):
            self.show_value(b, self.s.start)

    def schedule_save(self):
        if not self.persist:
            return
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(500, lambda: save_settings(self.s))

    # --- the box in its own thread ---

    def start(self):
        self.retry.grid_remove()
        if self.midi:
            self.midi.close()
            self.midi = None
        try:
            self.midi = self.make_midi()
        except MidiSetupError as e:
            self.show_error(str(e))
            return
        self.box.midi = self.midi
        self.out_status.config(text=f"● Output: NM2 Ratchet ({self.midi.where}). "
                                    "Select 'NM2 Ratchet' as your synth's MIDI input.", fg=GREEN)
        self.stop = threading.Event()
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.worker.start()

    def work(self):
        try:
            run(self.midi, self.box, "Bluetooth", self.stop)
        except Exception as e:   # shown in the window: a windowed .exe has no console
            self.events.put(("error", f"The box stopped: {type(e).__name__}: {e}"))

    def show_error(self, text):
        self.out_status.config(text=f"● {text}", fg=RED)
        self.retry.grid(row=2, column=0, sticky="w", pady=(4, 0))

    def set_nm2_status(self, kind, via=""):
        text, color = {
            "connected": (f"● NM2: connected over {via}", GREEN),
            "cannot": ("● NM2: found, but it can't be opened. Another program may be using it: untick the NM2 "
                       "in your synth/DAW, then unplug and replug it.", RED),
            "waiting": ("● NM2: waiting for it (plug in the USB cable or connect Bluetooth)", GREY),
        }[kind]
        self.nm2_status.config(text=text, fg=color)

    def show_value(self, b, v):
        _, _, bar, val, _ = self.rows[b]
        bar["value"] = v
        val.config(text=str(v))

    def show_held(self, b):
        for i, row in enumerate(self.rows):
            row[4].config(text="◀ held" if i == b else "")

    def poll(self):
        while True:
            try:
                kind, *a = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "press":
                self.show_held(a[0])
                self.show_value(*a)
            elif kind == "release":
                self.show_held(None)
                self.show_value(*a)
            elif kind == "value":
                self.show_value(*a)
            elif kind == "connected":
                self.set_nm2_status("connected", a[0])
            elif kind == "cannot":
                self.set_nm2_status("cannot")
            elif kind in ("gone", "waiting"):
                self.set_nm2_status("waiting")
                self.show_held(None)
            elif kind == "error":
                self.show_error(a[0])
        self.root.after(50, self.poll)

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(1)
        if self.midi:
            self.midi.close()
        if self.persist:
            save_settings(self.s)
        self.root.destroy()


def selftest():
    """Open the window with a fake NM2, play press + tilt, check what the window shows and what was sent."""
    from test_box import FakeMidi, gradual, scenario

    fake, done, results = FakeMidi(), threading.Event(), []
    root = tk.Tk()
    app = App(root, Settings(), lambda: fake, persist=False)
    app.rows[8][1].set(74)   # type CC 74 for button 9 in the table

    def play():
        time.sleep(0.5)
        scenario(fake)
        time.sleep(0.3)
        done.set()

    def check():
        if not done.is_set():
            root.after(100, check)
            return
        root.update()
        sent = [m[2] for m in fake.sent if m[:2] == [0xB0, 74]]
        results.append(("table edit reaches the box", app.s.buttons[8][0] == 74))
        results.append(("CC 74 goes 64 → 84 gradually", gradual(sent, 84)))
        results.append(("window shows 84 for button 9", app.rows[8][3].cget("text") == "84"))
        results.append(("bar shows 84", float(app.rows[8][2]["value"]) == 84))
        results.append(("NM2 shown as connected", "connected" in app.nm2_status.cget("text")))
        results.append(("encoder passed through", [0xB0, 1, 99] in fake.sent))
        app.close()

    threading.Thread(target=play, daemon=True).start()
    root.after(100, check)
    root.mainloop()
    say = print if sys.stdout else (lambda *_: None)   # the windowed .exe has no console
    for name, ok in results:
        say(("ok    " if ok else "FAIL  ") + name)
    ok = len(results) == 6 and all(ok for _, ok in results)
    say("PASS" if ok else "FAILED")
    sys.exit(0 if ok else 1)


def main():
    if sys.platform == "win32":
        try:   # sharp text on high-resolution screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if "--selftest" in sys.argv:
        selftest()
    root = tk.Tk()
    App(root, load_settings(), lambda: open_midi(DEFAULT, "NM2 Ratchet"))
    root.mainloop()


if __name__ == "__main__":
    main()
