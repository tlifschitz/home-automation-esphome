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

# Auto-discover the slave address (scans 1..32 by default) and poll
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX

# Faster path if you already know the address
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --slave 1

# One-shot read
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --slave 1 --once

# If the meter is on a non-default baud/parity, override:
python tools/m1m_debug.py --port /dev/tty.usbserial-XXXX --baud 9600 --parity E
```

### Reading the output

```
── slave 1 @ 18:24:07 ──
  Addr  Name                      Raw (hex words)                  Value
------------------------------------------------------------------------
0x5b02  Voltage L1                0000 08F4                     228.4 V
0x5b10  Current L1                0000 03C2                      9.62 A
0x5b1a  Active power total        0000 5588                    218.96 W
0x5b32  Frequency                 1389                          50.01 Hz
0x5000  Active energy import      0000 0000 0001 86A0          1000.00 kWh
```

The **Raw (hex words)** column is what's actually on the wire — useful
if the engineering value looks wrong: if the bytes look right but the
value is off, it's a scaling or sign issue; if the bytes themselves
look swapped (e.g. you expect 228.4 V but see something like 0x08F4
appearing in the wrong word position), it's a byte-order issue and you'd
need to use `U_DWORD_R`/`S_DWORD_R` in the ESPHome YAML instead of
`U_DWORD`/`S_DWORD`.

Confirm each Real-time value against what the meter shows on its
display. If they all match, the addresses in
`devices/abb-m1m-meter.yaml` are correct for your M1M generation.
