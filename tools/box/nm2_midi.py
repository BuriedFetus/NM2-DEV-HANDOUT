"""MIDI connection for the box, on Linux and Windows.

Both versions offer the same calls, so nm2_box.py doesn't care which one runs:
  ports()           {port: "USB" or "Bluetooth"} for every NM2 port
  connect(port)     start reading that NM2 port (True if it worked)
  disconnect(port)  stop reading it
  wait(timeout)     list of incoming messages (plain MIDI bytes), waits up to timeout seconds
  send(msg)         send one message (plain MIDI bytes) out of "NM2 Ratchet"
  close()           release all ports
  where             text saying where "NM2 Ratchet" is
Setup problems (no MIDI system, python-rtmidi missing, no loopMIDI port) raise MidiSetupError.

AlsaMidi (Linux): talks to libasound through ctypes, creates "NM2 Ratchet" itself. No extra packages.
RtMidi (Windows): uses python-rtmidi (pip install python-rtmidi) and sends to a loopMIDI port
named "NM2 Ratchet", because Windows can't create virtual MIDI ports itself.
"""

import ctypes as C
import queue
import select
import subprocess
import sys


class MidiSetupError(Exception):
    """Something to fix before the box can run; the message says what."""


def split(data):
    """Cut a run of MIDI bytes (every message with its status byte) into messages."""
    msgs, i = [], 0
    while i < len(data):
        s = data[i]
        if s < 0x80:            # stray data byte
            i += 1
            continue
        if s == 0xF0:           # system exclusive: up to and including 0xF7
            end = data.index(0xF7, i) + 1 if 0xF7 in data[i:] else len(data)
        elif s < 0xF0:
            end = i + (2 if s & 0xF0 in (0xC0, 0xD0) else 3)
        else:
            end = i + {0xF1: 2, 0xF2: 3, 0xF3: 2}.get(s, 1)
        msgs.append(list(data[i:end]))
        i = end
    return msgs


# --- Linux: ALSA sequencer through libasound ---

class Addr(C.Structure):
    _fields_ = [("client", C.c_ubyte), ("port", C.c_ubyte)]


class Event(C.Structure):  # snd_seq_event_t
    _fields_ = [("type", C.c_ubyte), ("flags", C.c_ubyte), ("tag", C.c_ubyte), ("queue", C.c_ubyte),
                ("time", C.c_uint * 2), ("source", Addr), ("dest", Addr), ("data", C.c_ubyte * 12)]


assert C.sizeof(Event) == 28


class PollFd(C.Structure):
    _fields_ = [("fd", C.c_int), ("events", C.c_short), ("revents", C.c_short)]


EV_NONE = 0
QUEUE_DIRECT, ADDR_SUBSCRIBERS, ADDR_UNKNOWN = 253, 254, 253
CAP_READ, CAP_WRITE, CAP_SUBS_READ, CAP_SUBS_WRITE = 1, 2, 0x20, 0x40
TYPE_MIDI_GENERIC, TYPE_APPLICATION = 2, 1 << 20


class AlsaMidi:
    def __init__(self, name):
        self.asound = a = C.CDLL("libasound.so.2")
        a.snd_midi_event_decode.restype = a.snd_midi_event_encode.restype = C.c_long
        a.snd_midi_event_decode.argtypes = [C.c_void_p, C.c_char_p, C.c_long, C.c_void_p]
        a.snd_midi_event_encode.argtypes = [C.c_void_p, C.c_char_p, C.c_long, C.c_void_p]
        self.h = C.c_void_p()
        if a.snd_seq_open(C.byref(self.h), b"default", 3, 1) < 0:  # duplex, non-blocking
            raise MidiSetupError("Cannot open the ALSA sequencer")
        a.snd_seq_set_client_name(self.h, name.encode())
        self.client = a.snd_seq_client_id(self.h)
        self.inp = a.snd_seq_create_simple_port(
            self.h, b"NM2 in", CAP_WRITE | CAP_SUBS_WRITE, TYPE_MIDI_GENERIC | TYPE_APPLICATION)
        self.out = a.snd_seq_create_simple_port(
            self.h, name.encode(), CAP_READ | CAP_SUBS_READ, TYPE_MIDI_GENERIC | TYPE_APPLICATION)
        self.where = f"MIDI port {self.client}:{self.out}"
        # libasound's own converters between sequencer events and plain MIDI bytes
        self.dec, self.enc = C.c_void_p(), C.c_void_p()
        a.snd_midi_event_new(256, C.byref(self.dec))
        a.snd_midi_event_new(256, C.byref(self.enc))
        a.snd_midi_event_no_status(self.dec, 1)  # every message keeps its status byte
        self.buf = C.create_string_buffer(256)
        n = a.snd_seq_poll_descriptors_count(self.h, select.POLLIN)
        fds = (PollFd * n)()
        a.snd_seq_poll_descriptors(self.h, fds, n, select.POLLIN)
        self.poller = select.poll()
        for f in fds:
            self.poller.register(f.fd, select.POLLIN)

    def ports(self):
        out = subprocess.run(["aseqdump", "-l"], capture_output=True, text=True).stdout
        return {line.split()[0]: "Bluetooth" if "Bluetooth" in line else "USB"
                for line in out.splitlines() if "NM2" in line and "Ratchet" not in line}  # skip our own port

    def connect(self, port):
        client, p = map(int, port.split(":"))
        return self.asound.snd_seq_connect_from(self.h, self.inp, client, p) >= 0

    def disconnect(self, port):
        client, p = map(int, port.split(":"))
        self.asound.snd_seq_disconnect_from(self.h, self.inp, client, p)

    def wait(self, timeout):
        self.poller.poll(timeout * 1000)
        msgs = []
        ev = C.POINTER(Event)()
        while self.asound.snd_seq_event_input(self.h, C.byref(ev)) >= 0:
            n = self.asound.snd_midi_event_decode(self.dec, self.buf, len(self.buf), ev)
            if n > 0:   # not a MIDI message (e.g. port announcements) gives an error: skip
                msgs += split(self.buf.raw[:n])
        return msgs

    def send(self, msg):
        ev = Event()
        self.asound.snd_midi_event_reset_encode(self.enc)
        data = bytes(msg)
        if self.asound.snd_midi_event_encode(self.enc, data, len(data), C.byref(ev)) <= 0 or ev.type == EV_NONE:
            return
        ev.queue = QUEUE_DIRECT
        ev.source.port = self.out
        ev.dest.client, ev.dest.port = ADDR_SUBSCRIBERS, ADDR_UNKNOWN
        self.asound.snd_seq_event_output_direct(self.h, C.byref(ev))

    def close(self):
        self.asound.snd_seq_close(self.h)


# --- Windows (also runs on Linux for testing): python-rtmidi ---

class RtMidi:
    def __init__(self, name):
        try:
            import rtmidi
        except ImportError:
            raise MidiSetupError("python-rtmidi is missing. Install it with:  py -m pip install python-rtmidi")
        self.out = rtmidi.MidiOut(name=name)
        found = [i for i, p in enumerate(self.out.get_ports()) if name in p]
        if found:
            self.out.open_port(found[0])
            self.where = f"port '{self.out.get_ports()[found[0]]}'"
        elif sys.platform != "win32":
            self.out.open_virtual_port(name)
            self.where = f"virtual port '{name}'"
        else:
            raise MidiSetupError(f"No MIDI port named '{name}'. Open loopMIDI, type {name} as the new port name, "
                                 "click +, then start the box again.")
        self.inp = rtmidi.MidiIn(name=name + " in")
        self.lister = rtmidi.MidiIn(name=name + " list")  # used only by the port watcher thread
        self.queue = queue.Queue()

    def ports(self):
        return {p: "Bluetooth" if "Bluetooth" in p else "USB"
                for p in self.lister.get_ports() if "NM2" in p and "Ratchet" not in p}

    def connect(self, port):
        try:
            self.inp.open_port(self.inp.get_ports().index(port))
        except Exception:   # gone again, or opened by another app (Windows allows only one)
            return False
        self.inp.set_callback(lambda event, _: self.queue.put(event[0]))
        return True

    def disconnect(self, port):
        self.inp.cancel_callback()
        self.inp.close_port()

    def wait(self, timeout):
        try:
            msgs = [self.queue.get(timeout=timeout)]
        except queue.Empty:
            return []
        while not self.queue.empty():
            msgs.append(self.queue.get_nowait())
        return msgs

    def send(self, msg):
        self.out.send_message(msg)

    def close(self):
        for port in (self.inp, self.out, self.lister):
            port.close_port()


def open_midi(kind, name):
    return AlsaMidi(name) if kind == "alsa" else RtMidi(name)


DEFAULT = "alsa" if sys.platform.startswith("linux") else "rtmidi"
