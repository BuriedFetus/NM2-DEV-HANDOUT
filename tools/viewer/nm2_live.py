#!/usr/bin/env python3
"""Live NM2 MIDI viewer.

Reads the NM2's MIDI (USB and/or Bluetooth) through `aseqdump` and streams it to a web page.
Run:  python3 tools/viewer/nm2_live.py   then open http://localhost:8765
      Box + synth simulator: http://localhost:8765/sim
Stop: Ctrl+C
"""

import json
import queue
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
PAGES = {
    "/": Path(__file__).with_name("nm2_live.html"),
    "/sim": Path(__file__).with_name("nm2_sim.html"),
}

# e.g. " 24:0   Note on                 0, note 69, velocity 100"
LINE = re.compile(r"^\s*(\d+:\d+)\s+(Note on|Note off|Control change)\s+(\d+), \w+ (\d+), \w+ (\d+)")

clients = set()
clients_lock = threading.Lock()


def find_nm2_ports():
    """Return {port: "USB" or "Bluetooth"} for every NM2 MIDI port."""
    out = subprocess.run(["aseqdump", "-l"], capture_output=True, text=True).stdout
    return {line.split()[0]: "Bluetooth" if "Bluetooth" in line else "USB"
            for line in out.splitlines() if "NM2" in line and "Ratchet" not in line}  # skip the box's own port


def broadcast(event):
    data = json.dumps(event)
    with clients_lock:
        for q in clients:
            q.put(data)


def watch_ports(proc, ports):
    # Restart aseqdump when an NM2 port appears or goes away (e.g. Bluetooth connects while on USB).
    while proc.poll() is None:
        time.sleep(2)
        if find_nm2_ports() != ports:
            proc.terminate()
            return


def read_midi():
    # aseqdump keeps running after a USB drop but stops receiving ("Port unsubscribed"),
    # so restart it whenever that happens and wait for the NM2 to come back.
    while True:
        ports = find_nm2_ports()
        if not ports:
            time.sleep(1)
            continue
        via = " + ".join(sorted(set(ports.values()), reverse=True))
        print(f"NM2 connected via {via} (MIDI port {', '.join(ports)})", flush=True)
        broadcast({"t": time.time() * 1000, "kind": "connected", "via": via})
        proc = subprocess.Popen(["aseqdump", "-p", ",".join(ports)], stdout=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=watch_ports, args=(proc, ports), daemon=True).start()
        for line in proc.stdout:
            if "Port unsubscribed" in line:
                proc.terminate()
                break
            m = LINE.match(line)
            if not m:
                continue
            port, kind = m.group(1), m.group(2)
            ch, num, val = int(m.group(3)), int(m.group(4)), int(m.group(5))
            if kind == "Note on" and val == 0:
                kind = "Note off"
            broadcast({"t": time.time() * 1000, "kind": kind, "ch": ch + 1, "num": num, "val": val,
                       "src": ports.get(port, "?")})
        proc.wait()
        print("NM2 disconnected, waiting for it to come back…", flush=True)
        broadcast({"t": time.time() * 1000, "kind": "disconnected"})
        time.sleep(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in PAGES:
            body = PAGES[self.path].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = queue.Queue()
            with clients_lock:
                clients.add(q)
            try:
                while True:
                    try:
                        self.wfile.write(f"data: {q.get(timeout=15)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with clients_lock:
                    clients.discard(q)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


def main():
    if not find_nm2_ports():
        print("NM2 not found yet. Plug it in over USB or connect it over Bluetooth; it will be picked up automatically.")
    threading.Thread(target=read_midi, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    print(f"Open http://localhost:{PORT} or http://localhost:{PORT}/sim  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
