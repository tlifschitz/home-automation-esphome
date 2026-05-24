# tools/

Bench utilities — these run on your laptop, NOT on the ESP. They exist
to validate things before flashing.

## `m1m_debug.py`

Reads the ABB M1M over Modbus RTU using a USB-RS485 dongle and prints
each register's raw words alongside its scaled engineering value, so
you can compare directly with the meter's front-panel display.

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r tools/requirements.txt
```

### Usage

```bash
# Find your dongle's device name
python tools/m1m_debug.py --list-ports

# Hardware loopback test (verify the USB-serial path before suspecting the meter)
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --loopback

# Auto-discover the slave address (scans 1..32 by default) and poll
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX

# Faster path if you already know the address
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --slave 1

# One-shot read
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --slave 1 --once

# If the meter is on a non-default baud/parity, override:
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --baud 9600 --parity E
```

### When the Modbus side isn't responding

Run the loopback test first to split the problem in half:

- **Loopback passes, Modbus still fails** → the USB-serial path is good;
  the issue is downstream (wiring to the meter, A/B swapped, baud/parity
  mismatch with the meter, or wrong slave address).
- **Loopback fails** → the problem is upstream of the bus (wrong serial
  port selected, dongle not actually plugged in, bad jumper, or a manual-
  direction RS485 dongle that physically can't loop back through itself).

Wiring for the loopback:

- **USB-TTL adapter + separate MAX485 module:** jumper the FTDI/CH340's
  TX pin to its RX pin (before the MAX485).
- **USB-RS485 dongle, auto-direction:** disconnect the meter from the A/B
  bus and run it as-is — most auto-direction dongles loop back internally.
- **USB-RS485 dongle, manual DE/RE control:** you can't loopback through
  one of these. Skip this test and trust the dongle, or grab an auto-
  direction model.

### Hard-won notes about USB ↔ RS485 setups

> Read this before wiring up any new Modbus device. It will save you an
> evening.

**A bare MAX485 module on a USB-TTL cable does NOT work for Modbus**,
even if every other thing about your setup is correct. The MAX485 is
half-duplex: it needs a direction-control signal (DE/RE) that flips to
*transmit* before each request and back to *receive* before the slave's
reply arrives — typically within 1–2 ms at 19200 baud.

The two control lines a USB-TTL cable exposes (DTR, RTS) are USB modem
control signals, set via USB control transfers with **5–20 ms of
latency**. By the time the OS/driver gets around to flipping DTR, the
slave has already finished replying. You get a perfect-looking loopback
test (which only proves the USB-TTL path itself works) and complete
silence when you talk to the meter.

This is a **hardware-level limitation**. No amount of Python, no choice
of OS, no pymodbus config flag fixes it.

#### What actually works

| Approach | Works on macOS? | Cost | Notes |
|---|---|---|---|
| Auto-direction TTL↔RS485 module (XY-017, MAX13487-based, etc.) | Yes | ~$3 | Same VCC/GND/A/B/TX/RX pinout as a MAX485 board — drop-in. Direction control happens inside the module. |
| Replace MAX485 with MAX13487 chip on existing board | Yes | ~$2 | Pin-compatible auto-direction transceiver. Harder to source. |
| FT232R + TXDEN (CBUS pin programmed via FT_Prog) | Yes (after one-time Windows setup) | $0 if you have one | Real FT232R only; FT_Prog runs on Windows; settings persist in the chip's EEPROM. |
| Drive DE/RE from an MCU GPIO (ESP/Arduino as a Modbus master) | Yes | $0 if you have one | This is what `devices/abb-m1m-meter.yaml` does — GPIO5 toggles in microseconds. |
| pyserial `rs485_mode` with kernel TIOCSRS485 ioctl | Linux only, and only with driver support | $0 | Don't try this on macOS. |

#### Identifying which USB-serial chip you actually have

The "Manufacturer" string in a USB descriptor is often marketing nonsense
(CH340 cables routinely claim to be "FTDI"). The **Vendor ID** is the
ground truth:

```bash
system_profiler SPUSBDataType | grep -B2 -A10 -i 'usb serial\|ftdi\|prolific\|wch\|silicon labs'
```

| Vendor ID | Chip family | TXDEN auto-direction? |
|---|---|---|
| `0x0403` | FTDI (FT232R, FT232H, FT2232, etc.) | Only on FT232R/RL |
| `0x1a86` | WCH / QinHeng (CH340, CH341) | No |
| `0x10c4` | Silicon Labs (CP2102, CP2104, CP2108) | No |
| `0x067b` | Prolific (PL2303) | No |

If you see `0x1a86` or `0x10c4` or `0x067b`: don't bother with FT_Prog,
get an auto-direction module.

#### The simplest path for this repo

The ESP-based design in `devices/abb-m1m-meter.yaml` is the correct
solution for talking to a Modbus device from your network — the ESP's
GPIO can flip in microseconds, which is what RS485 direction control
actually needs. The Python `m1m_debug.py` tool is for **pre-flight
verification only**, and it needs auto-direction silicon (either a
proper USB-RS485 dongle, or an auto-direction TTL↔RS485 module on a
USB-TTL cable) to be useful for talking to the meter. Loopback mode
works against any USB-TTL hardware regardless.

### Reading the output

```
── slave 1 @ 18:24:07 ──
 Addr  Name                      Raw (hex words)            Value
-----------------------------------------------------------------------
  102  Active power L1           0000 4340                    195.0 W
  118  Power factor L1           0000 3F66                    0.898
  126  Apparent power L1         0000 4359                    217.0 VA
  142  Voltage L1 (L-N)          0000 4364                    228.4 V
  150  Current L1                CCCD 3F19                     0.60 A
  156  Frequency                 0000 4248                    50.01 Hz
  158  Energy imported           86A0 0001                  100000 Wh
```

The **Raw (hex words)** column is what's actually on the wire — useful
if the engineering value looks wrong: if the bytes look right but the
value is off, it's likely a byte-order issue (try `decode_float_cdab`
vs. a non-swapped variant); if the address itself is reading 0xFFFF or
garbage, the register doesn't exist at that address on this meter.

Confirm each value against what the meter shows on its front-panel
display. If they all match, the addresses in
`devices/abb-m1m-meter.yaml` are correct for your meter.

### Register map

This script reads the **legacy M1M 12 register map** — 32-bit IEEE 754
floats at decimal addresses 100..160, word-swapped (CDAB) byte order.
That matches the older M1M 10/12 generation. **It does NOT match the
M1M 15/20/30 family** in the "M1M 96 Modbus Manual V1.3C" (those use
scaled integers at 0x5B00..). Don't be fooled by ABB grouping them
under the same product family — the wire formats are completely
different. If you adapt this script for an M1M 15/20/30, you'll need
to rewrite the `REGISTERS` catalog with the modern addresses and
switch the decoder from `decode_float_cdab` to scaled-integer math.
