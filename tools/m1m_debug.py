#!/usr/bin/env python3
"""
m1m_debug.py — Read the ABB M1M 12 power meter over Modbus RTU from a
laptop and print its registers, so you can sanity-check addresses against
the meter's front-panel display before flashing the ESP.

Reads the LEGACY M1M 12 register map (32-bit floats at decimal addresses
100..160, word-swapped CDAB byte order) — NOT the M1M 96 manual's
scaled-integer 0x5B00 layout (which applies to M1M 15/20/30 only).

Hardware
--------
USB-RS485 dongle (any CH340/FTDI-based "USB to RS485" adapter), wired:

    Dongle A  ────  M1M terminal A
    Dongle B  ────  M1M terminal B
    Dongle GND ───  M1M terminal C   (optional, recommended)

If you have only ONE device on the bus (the M1M), no termination is
strictly required. Add a 120 Ω resistor across A↔B at the meter end if
you see CRC errors on a long run.

Usage
-----
    # First, see which serial port your dongle showed up as:
    python tools/m1m_debug.py --list-ports

    # Hardware loopback test (jumper TX↔RX, or use an auto-echo RS485 dongle
    # with the meter unplugged) — confirms the dongle + driver path works:
    python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --loopback

    # Then either let the script discover the slave address:
    python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX

    # ...or specify it explicitly:
    python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --slave 1

    # One-shot read (no polling loop):
    python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --once

Install
-------
    pip install -r tools/requirements.txt
"""

import argparse
import struct
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    sys.exit("pymodbus not installed. Run: pip install -r tools/requirements.txt")

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial not installed. Run: pip install -r tools/requirements.txt")


# ---------------------------------------------------------------------------
# Register catalog — keep this in sync with devices/abb-m1m-meter.yaml
#
# The M1M 12 uses the LEGACY ABB M1M register map: 32-bit IEEE 754 floats
# in the 100..160 decimal address range, word-swapped (CDAB) byte order.
# This is NOT the M1M 96 manual's 0x5B00 scaled-integer layout — that map
# applies to the M1M 15/20/30 series.
#
# Per-phase quantities are laid out [Total, L1, L2, L3] back-to-back
# (2 registers each, phase stride +2). For single-phase use, read L1.
# ---------------------------------------------------------------------------


@dataclass
class Register:
    address: int       # holding-register address (function code 0x03)
    name: str
    unit: str
    decimals: int = 2
    # The legacy M1M 12 is float-only for measurements; the one non-float
    # entry is "Load seconds" at 216 (u32, word-swapped) — set is_float=False
    # to decode it via decode_u32_cdab() instead.
    is_float: bool = True


REGISTERS: List[Register] = [
    Register(102, "Active power L1",     "W",   decimals=1),
    Register(118, "Power factor L1",     "",    decimals=3),
    Register(126, "Apparent power L1",   "VA",  decimals=1),
    Register(142, "Voltage L1 (L-N)",    "V",   decimals=1),
    Register(150, "Current L1",          "A",   decimals=2),
    Register(156, "Frequency",           "Hz",  decimals=2),
    Register(158, "Energy imported",     "Wh",  decimals=0),
    Register(160, "Apparent energy",     "VAh", decimals=0),
    Register(216, "Load seconds",        "s",   decimals=0, is_float=False),
    # --- Useful totals (uncomment to also dump three-phase aggregates) ---
    # Register(100, "Active power total",   "W",   decimals=1),
    # Register(116, "Power factor avg",     "",    decimals=3),
    # Register(124, "Apparent power total", "VA",  decimals=1),
    # Register(140, "Voltage avg (L-N)",    "V",   decimals=1),
    # Register(148, "Current total",        "A",   decimals=2),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def decode_float_cdab(regs: List[int]) -> float:
    """Decode an M1M 12 word-swapped (CDAB) IEEE 754 float.

    The meter sends 4 bytes such that minimalmodbus / pymodbus reads them
    into two 16-bit registers where reg[0] is the LOW word and reg[1] is
    the HIGH word — i.e. swapped relative to standard Modbus big-endian.
    This matches ESPHome's value_type: FP32_R.
    """
    if len(regs) < 2:
        raise ValueError("decode_float_cdab needs 2 registers")
    # Swap word order so [low, high] -> [high, low], then big-endian decode.
    packed = struct.pack(">HH", regs[1] & 0xFFFF, regs[0] & 0xFFFF)
    return struct.unpack(">f", packed)[0]


def decode_u32_cdab(regs: List[int]) -> int:
    """Decode a word-swapped 32-bit unsigned int (matches the float layout)."""
    if len(regs) < 2:
        raise ValueError("decode_u32_cdab needs 2 registers")
    return ((regs[1] & 0xFFFF) << 16) | (regs[0] & 0xFFFF)


def list_ports() -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports detected.")
        return
    print("Detected serial ports:")
    for p in ports:
        print(f"  {p.device:<25}  {p.description}")


def loopback(port: str, baud: int, parity: str, stopbits: int) -> int:
    """Raw serial loopback. Sends 0x00..0xFF, reads back, compares.

    Wiring options:
      • USB-TTL adapter: short TX↔RX with a jumper wire.
      • USB-RS485 dongle with auto-direction transceiver: the chip
        usually echoes locally — just unplug the M1M from the bus
        first so it doesn't reply on top of the echo.
      • USB-RS485 dongle with manual DE/RE direction control: a true
        loopback isn't possible (half-duplex on one differential pair
        with the line driver disabled while receiving).

    Returns the shell exit code: 0 OK, 2 nothing back, 3 mismatch.
    """
    pattern = bytes(range(256))

    print(f"Loopback test on {port}")
    print(f"  Settings: {baud} baud, 8{parity}{stopbits}")
    print(f"  Sending {len(pattern)} bytes (0x00..0xFF), expecting echo back.")
    print(f"  Reminder: jumper TX↔RX, or rely on RS485 auto-echo with the")
    print(f"  meter disconnected from the bus.")
    print()

    # Per-call timeout: time to TX + RX + slack
    bit_time = (len(pattern) * 10) / baud
    timeout = bit_time * 2 + 0.5

    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            parity=parity,
            stopbits=stopbits,
            bytesize=8,
            timeout=timeout,
        )
    except serial.SerialException as exc:
        print(f"✗ Failed to open {port}: {exc}")
        return 2

    with ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(pattern)
        ser.flush()
        received = ser.read(len(pattern))

    if not received:
        print(f"✗ Nothing received within {timeout:.1f}s.")
        print()
        print("  Likely causes:")
        print("    - TX and RX aren't actually shorted (or the jumper has a bad contact).")
        print("    - You're on a half-duplex RS485 dongle with manual DE/RE control —")
        print("      it physically can't loop back through itself. Either:")
        print("        a) switch to an auto-direction dongle, or")
        print("        b) skip the loopback test and verify with the meter present.")
        print("    - Wrong --port. Run with --list-ports to double-check.")
        return 2

    if received == pattern:
        print(f"✓ Loopback OK: received all {len(received)} bytes correctly.")
        print(f"  The USB-serial path is good. If Modbus to the meter still")
        print(f"  fails, the problem is downstream of the dongle (wiring to the")
        print(f"  meter, A/B swapped, baud/parity mismatch, or meter address).")
        return 0

    matches = sum(1 for a, b in zip(received, pattern) if a == b)
    print(f"⚠ Mismatch: received {len(received)} / {len(pattern)} bytes "
          f"({matches} match).")
    print(f"  Sent first 16:     {pattern[:16].hex(' ')}")
    print(f"  Received first 16: {received[:16].hex(' ')}")
    print()
    print("  Mismatches usually mean line noise (try a slower --baud), or the")
    print("  echo coming back through a different framing (parity/stopbits set")
    print("  the way the dongle interprets the loopback bytes).")
    return 3


def discover(client: ModbusSerialClient, start: int, end: int) -> Optional[int]:
    """Scan slave addresses, return the first one that responds to a
    voltage-register read. Most installations have the meter at address 1,
    so the default scan window is small for speed."""
    print(f"Scanning addresses {start}..{end} for a responsive slave...")
    for addr in range(start, end + 1):
        sys.stdout.write(f"\r  addr {addr:3d}...   ")
        sys.stdout.flush()
        try:
            # Read VLN L1 (addr 142, 2 registers = one float). Any non-error
            # response means the slave is alive at this address.
            result = client.read_holding_registers(address=142, count=2, slave=addr)
        except Exception:
            continue
        if result is not None and not result.isError():
            print(f"\n  ✓ slave responds at address {addr}\n")
            return addr
    print("\n  ✗ no slave found in that range\n")
    return None


def dump_once(client: ModbusSerialClient, slave: int) -> None:
    """Read every register in REGISTERS and print a table."""
    ts = time.strftime("%H:%M:%S")
    print(f"\n── slave {slave} @ {ts} ──")
    header = f"{'Addr':>5}  {'Name':<24}  {'Raw (hex words)':<14}  {'Value':>16}"
    print(header)
    print("-" * len(header))

    for r in REGISTERS:
        try:
            result = client.read_holding_registers(
                address=r.address, count=2, slave=slave
            )
        except Exception as exc:
            print(f"{r.address:>5}  {r.name:<24}  <exception: {exc}>")
            continue

        if result is None or result.isError():
            print(f"{r.address:>5}  {r.name:<24}  {'<error>':<14}  {'-':>16}")
            continue

        raw_hex = " ".join(f"{w:04X}" for w in result.registers)
        try:
            if r.is_float:
                value = decode_float_cdab(result.registers)
            else:
                value = decode_u32_cdab(result.registers)
        except Exception as exc:
            print(f"{r.address:>5}  {r.name:<24}  {raw_hex:<14}  <decode: {exc}>")
            continue

        value_str = f"{value:.{r.decimals}f} {r.unit}".strip()
        print(f"{r.address:>5}  {r.name:<24}  {raw_hex:<14}  {value_str:>16}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--port", help="Serial device, e.g. /dev/tty.usbserial-XXXX")
    ap.add_argument("--baud", type=int, default=19200,
                    help="Baud rate (default: 19200)")
    ap.add_argument("--parity", choices=["N", "E", "O"], default="N",
                    help="Parity (default: N)")
    ap.add_argument("--stopbits", type=int, default=1,
                    help="Stop bits (default: 1)")
    ap.add_argument("--slave", type=int,
                    help="Slave address. Omit to auto-discover.")
    ap.add_argument("--scan-start", type=int, default=1,
                    help="First slave address to scan (default: 1)")
    ap.add_argument("--scan-end", type=int, default=32,
                    help="Last slave address to scan (default: 32). "
                         "Pass --scan-end 247 to scan the full Modbus range.")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="Seconds between dumps (default: 5)")
    ap.add_argument("--once", action="store_true",
                    help="Print one dump and exit")
    ap.add_argument("--list-ports", action="store_true",
                    help="List available serial ports and exit")
    ap.add_argument("--loopback", action="store_true",
                    help="Hardware loopback test: send 0x00..0xFF on the port "
                         "and verify it comes back. Jumper TX↔RX, or unplug "
                         "the meter and rely on an auto-echo RS485 dongle.")
    ap.add_argument("--timeout", type=float, default=1.0,
                    help="Per-request timeout in seconds (default: 1.0)")
    args = ap.parse_args()

    if args.list_ports:
        list_ports()
        return

    if not args.port:
        print("No --port specified. Available ports:\n")
        list_ports()
        sys.exit("\nRe-run with --port <device>.")

    if args.loopback:
        rc = loopback(args.port, args.baud, args.parity, args.stopbits)
        sys.exit(rc)

    client = ModbusSerialClient(
        port=args.port,
        baudrate=args.baud,
        parity=args.parity,
        stopbits=args.stopbits,
        bytesize=8,
        timeout=args.timeout,
    )
    if not client.connect():
        sys.exit(f"Failed to open serial port {args.port}")

    try:
        slave = args.slave
        if slave is None:
            slave = discover(client, args.scan_start, args.scan_end)
            if slave is None:
                sys.exit(
                    "No slave found. Check:\n"
                    "  • wiring (A↔A, B↔B)\n"
                    "  • baud, parity, stop bits match meter front-panel\n"
                    "  • RS485 dongle DE/RE is wired correctly (or auto-direction)\n"
                    "  • re-scan wider with --scan-end 247"
                )

        if args.once:
            dump_once(client, slave)
            return

        print(f"Polling every {args.interval:g}s. Ctrl-C to stop.")
        while True:
            dump_once(client, slave)
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
