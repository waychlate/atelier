"""Relays the wand's whole data stream from USB serial to the server, over
plain loopback HTTP calls - no Wi-Fi involved anywhere in this path. The
firmware (esp32/src/main.cpp) has no network stack at all any more; this
script is the wand's only connection to the server.

Two line prefixes, both newline-terminated:
- "L:" - one live sample, printed at 50 Hz the whole time, idle included
  (print_live_sample). Relayed to POST /stroke/live for the live cursor.
  A dropped one isn't worth stopping over - the next sample corrects it.
- "S:" - the complete letter, printed once on submit (submit_letter).
  Relayed to POST /stroke for grading; the response (score/feedback) is
  printed here since the wand has no LEDs/buzzer to show it on.

Requires pyserial: pip install pyserial

Usage:
    python scripts/serial_bridge.py --port /dev/ttyUSB0
    python scripts/serial_bridge.py            # auto-detect the port
"""

import argparse
import json
import sys
import urllib.request

import serial
import serial.tools.list_ports

BAUD_RATE = 921600  # must match esp32/src/main.cpp's Serial.begin() and platformio.ini
LIVE_PREFIX = "L:"
STROKE_PREFIX = "S:"

# Common ESP32 dev-board USB-UART bridge chips, for --port auto-detection.
KNOWN_VID_PID = {
    (0x10C4, 0xEA60),  # Silicon Labs CP210x
    (0x1A86, 0x7523),  # QinHeng CH340
    (0x1A86, 0x55D4),  # QinHeng CH9102
}


def find_port() -> str:
    candidates = [
        p for p in serial.tools.list_ports.comports() if (p.vid, p.pid) in KNOWN_VID_PID
    ]
    if not candidates:
        sys.exit(
            "No ESP32-looking serial port found. Pass one explicitly: --port /dev/ttyUSB0\n"
            f"Ports seen: {[p.device for p in serial.tools.list_ports.comports()] or 'none'}"
        )
    if len(candidates) > 1:
        sys.exit(
            "Multiple candidate ports found, pass one explicitly: --port ...\n"
            f"Candidates: {[p.device for p in candidates]}"
        )
    return candidates[0].device


def post_live_sample(base_url: str, payload: dict) -> None:
    req = urllib.request.Request(
        f"{base_url}/stroke/live",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1) as resp:
            resp.read()
    except Exception as e:
        # A dropped live-cursor point isn't worth stopping the stream over -
        # the next sample corrects the on-screen position either way.
        print(f"[bridge] live POST failed: {e}", file=sys.stderr)


def post_stroke(base_url: str, payload: dict) -> None:
    req = urllib.request.Request(
        f"{base_url}/stroke",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        print(f"[bridge] scored: {result}")
    except Exception as e:
        print(f"[bridge] stroke POST failed: {e}", file=sys.stderr)


def handle_line(line: str, base_url: str) -> None:
    if line.startswith(LIVE_PREFIX):
        try:
            sample = json.loads(line[len(LIVE_PREFIX) :])
        except json.JSONDecodeError:
            return  # garbled (e.g. the port opened mid-line) - the next one recovers
        post_live_sample(base_url, sample)
    elif line.startswith(STROKE_PREFIX):
        try:
            packet = json.loads(line[len(STROKE_PREFIX) :])
        except json.JSONDecodeError:
            print("[bridge] couldn't parse the submitted letter, dropped", file=sys.stderr)
            return
        post_stroke(base_url, packet)
    elif line:
        print(line)  # pass through the wand's normal debug logging


def run(port: str, base_url: str) -> None:
    print(f"[bridge] opening {port} @ {BAUD_RATE} baud")
    # Assembles lines by hand instead of ser.readline(): pyserial's readline
    # gives up on a line after the port timeout, and a whole submitted
    # letter ("S:" line, up to ~100 KB) can take longer than that to arrive.
    pending = bytearray()
    with serial.Serial(port, BAUD_RATE, timeout=0.1) as ser:
        while True:
            try:
                chunk = ser.read(ser.in_waiting or 1)
            except serial.SerialException as e:
                sys.exit(f"[bridge] serial port lost: {e}")
            if not chunk:
                continue
            pending += chunk
            if b"\n" not in chunk:
                continue
            *lines, rest = pending.split(b"\n")
            pending = bytearray(rest)
            for raw in lines:
                handle_line(raw.decode(errors="replace").rstrip(), base_url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial device, e.g. /dev/ttyUSB0 (auto-detected if omitted)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    run(args.port or find_port(), args.base_url)


if __name__ == "__main__":
    main()
