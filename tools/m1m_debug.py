#!/usr/bin/env python3
"""
m1m_debug.py — Read the ABB M1M power meter over Modbus RTU from a laptop
and print its registers, so you can sanity-check the addresses/scaling
against the meter's front-panel display.

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
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    sys.exit("pymodbus not installed. Run: pip install -r tools/requirements.txt")

try:
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial not installed. Run: pip install -r tools/requirements.txt")


# ---------------------------------------------------------------------------
# Register catalog — keep this in sync with devices/abb-m1m-meter.yaml
# Addresses from "M1M 96 Modbus Manual V1.3C" §4.2 and §4.3.
# ---------------------------------------------------------------------------

@dataclass
class Register:
    address: int       # holding-register address (function code 0x03)
    name: str
    n_regs: int        # 1 (16-bit), 2 (32-bit), or 4 (64-bit)
    signed: bool
    scale: float       # raw value * scale = engineering value
    unit: str
    decimals: int = 2


REGISTERS: List[Register] = [
    # --- Real-time data (§4.3) ---
    Register(0x5B02, "Voltage L1",            2, False, 0.1,   "V",   decimals=1),
    Register(0x5B10, "Current L1",            2, False, 0.01,  "A",   decimals=2),
    Register(0x5B1A, "Active power total",    2, True,  0.01,  "W",   decimals=1),
    Register(0x5B22, "Reactive power total",  2, True,  0.01,  "var", decimals=1),
    Register(0x5B2A, "Apparent power total",  2, True,  0.01,  "VA",  decimals=1),
    Register(0x5B32, "Frequency",             1, False, 0.01,  "Hz",  decimals=2),
    Register(0x5B40, "Power factor total",    1, True,  0.001, "",    decimals=3),
    # --- Energy counters (§4.2) ---
    Register(0x5000, "Active energy import",  4, False, 0.01,  "kWh", decimals=2),
    Register(0x5004, "Active energy export",  4, False, 0.01,  "kWh", decimals=2),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def decode_regs(regs: List[int], n_regs: int, signed: bool) -> int:
    """Combine N consecutive 16-bit registers into one int.

    Modbus is big-endian: the first register holds the most-significant
    word. Two's-complement is applied for signed types.
    """
    value = 0
    for r in regs[:n_regs]:
        value = (value << 16) | (r & 0xFFFF)
    if signed:
        sign_bit = 1 << (n_regs * 16 - 1)
        if value & sign_bit:
            value -= 1 << (n_regs * 16)
    return value


def list_ports() -> None:
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports detected.")
        return
    print("Detected serial ports:")
    for p in ports:
        print(f"  {p.device:<25}  {p.description}")


def discover(client: ModbusSerialClient, start: int, end: int) -> Optional[int]:
    """Scan slave addresses, return the first one that responds to a
    voltage-register read. Most installations have the meter at address 1,
    so the default scan window is small for speed."""
    print(f"Scanning addresses {start}..{end} for a responsive slave...")
    for addr in range(start, end + 1):
        sys.stdout.write(f"\r  addr {addr:3d}...   ")
        sys.stdout.flush()
        try:
            result = client.read_holding_registers(address=0x5B02, count=2, slave=addr)
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
    header = f"{'Addr':>6}  {'Name':<24}  {'Raw (hex words)':<22}  {'Value':>16}"
    print(header)
    print("-" * len(header))

    for r in REGISTERS:
        try:
            result = client.read_holding_registers(
                address=r.address, count=r.n_regs, slave=slave
            )
        except Exception as exc:
            print(f"{r.address:#06x}  {r.name:<24}  <exception: {exc}>")
            continue

        if result is None or result.isError():
            print(f"{r.address:#06x}  {r.name:<24}  {'<error>':<22}  {'-':>16}")
            continue

        raw_int = decode_regs(result.registers, r.n_regs, r.signed)
        scaled = raw_int * r.scale
        raw_hex = " ".join(f"{w:04X}" for w in result.registers)
        value_str = f"{scaled:.{r.decimals}f} {r.unit}".strip()
        print(f"{r.address:#06x}  {r.name:<24}  {raw_hex:<22}  {value_str:>16}")


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
