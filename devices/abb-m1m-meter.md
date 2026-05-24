# ABB M1M power meter

Single-phase energy monitor: ESP8266 reads the ABB M1M over Modbus RTU
and publishes to Home Assistant.

## Bill of materials

- Wemos D1 mini (ESP8266)
- MAX485 module with DE/RE pin (or an isolated RS485 transceiver for
  galvanic isolation from the mains-referenced meter)
- 120 Ω termination resistor (one, at the far end of the bus)
- Twisted-pair cable for the A/B differential pair
- 5 V supply for the D1 mini

## Wiring

```
   Wemos D1 mini                  MAX485 module                    M1M
   ─────────────                  ─────────────                    ───
        5V ────────────────────── VCC
       GND ────────────────────── GND
   D8 / GPIO15  ──────────────── DI
   D7 / GPIO13  ──────────────── RO
   D1 / GPIO5   ───┬─────────── DE
                   └─────────── RE        (tie DE+RE together)
                                  A ──── twisted ──── A
                                  B ──── twisted ──── B
                                GND ────────────────── C  (Common, optional)

   Termination: 120 Ω across A↔B at the M1M end.
```

GPIO13/15 = UART0 swap, so the default USB serial pins (GPIO1/3) stay
free for `esphome logs` over USB during bring-up.

## Meter settings (front panel)

These must match the `modbus_*` substitutions in `abb-m1m-meter.yaml`.
The values I'm shipping the YAML with:

- Modbus address:  1
- Baud:            19200
- Parity:          NONE
- Stop bits:       1

If yours differ, either change the meter or change the YAML — both must
agree. The next section walks through reading and changing them from the
front panel.

## Reading & changing Modbus settings on the M1M 12 front panel

The M1M 12 has two buttons on the front: **UP (▲)** and **DOWN (▼)**.
Their behavior depends on mode:

| Mode                  | UP                                     | DOWN                       |
|-----------------------|----------------------------------------|----------------------------|
| RUN (normal display)  | Scroll through measurement pages       | Scroll through pages       |
| SETUP, viewing a param| Advance to next parameter              | Enter edit mode for it     |
| SETUP, editing a value| Cycle the value / decrement the digit  | Accept and move on         |

### 1. Enter SETUP mode

Press **UP + DOWN simultaneously**. The display shows:

```
Row 1:  0000          ← first digit blinking
Row 2:  SEt.CLr
```

### 2. Enter the password `1000`

The first digit blinks; press **UP** to cycle it (the meter cycles
0 → 9 → 8 → … → 1, so nine UP presses to reach `1`). Press **DOWN** to
accept that digit and advance to the next one. The remaining three
digits stay at `0`, so just press **DOWN** three more times to accept
them.

### 3. Walk to the communication parameters

From the password screen, keep pressing **UP** to advance through the
parameter list. Watch Row 2 for the tag of the current parameter:

| Row 2 tag | Parameter             | Row 1 shows                       |
|-----------|-----------------------|-----------------------------------|
| `ELEA`    | Power system          | `StAr` / `dELt` / `1.Ph`          |
| `PPri`    | PT primary            | 4-digit voltage                   |
| `PSEC`    | PT secondary          | 100 / 110 / 120 V                 |
| `CPri`    | CT primary            | 4-digit current                   |
| `CSEC`    | CT secondary          | 1 / 5 A                           |
| `rEUL`    | Reverse lock          | `no` / `YES`                      |
| `URSt`    | VA computation method | `Arth` / `UECt` / `UECH`          |
| **`bAUd`**| **Baud rate**         | `2400` / `4800` / `9600` / `19.20k` |
| **`PrtY`**| **Parity**            | `EUEn` / `odd` / `no`             |
| **`dUId`**| **Modbus address**    | 1 – 247                           |
| `PUd`     | User password         | `----` (hidden)                   |
| `EnEr`    | Energy display format | `rESL` / `Cntr`                   |
| `ESEL`    | Energy unit           | `Wh` / `VAh`                      |

The three rows in bold are the ones to verify against the YAML.

### 4. Change a value

When the parameter you want is on the display:

1. Press **DOWN** — Row 1 starts blinking (you're now in edit mode).
2. Press **UP** to cycle through the options (for `bAUd` / `PrtY`) or
   to change the current digit (for `dUId`).
3. For multi-digit values like `dUId`, press **DOWN** to accept the
   current digit and move to the next.
4. After the last digit (or the only option), pressing **DOWN** commits
   the value and advances to the next parameter.

### 5. Exit

Either press **UP** until you've cycled past every parameter (the meter
returns to RUN mode automatically), or wait for the inactivity timeout.

### Factory defaults (per the M1M 12 user manual)

| Parameter   | Default   |
|-------------|-----------|
| Baud rate   | `9600`    |
| Parity      | `EUEn` (Even) — shown in the manual's example |
| Address     | `1`       |
| Password    | `1000`    |

> **Stop bits aren't user-configurable.** The M1M 12 spec sheet
> (page 2 of the user manual) lists "Stop bit: 1,2" as supported on the
> wire, but there's no setup step for it — the meter uses a fixed
> frame format keyed off the parity choice. The YAML defaults to
> `stop_bits: 1`. If the bus stays silent with parity = `NONE`, try
> `stop_bits: 2`.

### Useful detail: the RS485 port is optically isolated

The M1M 12's spec sheet calls out "RS485 with optical isolation" — the
meter takes care of galvanic isolation from the mains-referenced
measurement side, so a bare MAX485 module on the ESP is electrically
safe. You only need an isolated transceiver if you're paranoid about
ground loops on a long run.

## Flashing

```bash
cd <repo>
cp secrets.yaml.example secrets.yaml          # first time only
$EDITOR secrets.yaml
esphome run devices/abb-m1m-meter.yaml
```

After the first USB flash, updates go OTA over WiFi.

## Register map (and why it's different from the M1M 96 manual)

The M1M 12 uses the **legacy ABB M1M register map** that was inherited
from the older M1M 10/12 generation: 32-bit IEEE 754 floats at decimal
addresses 100..160, word-swapped (CDAB) byte order. This is **not** the
same as the M1M 15/20/30 family map in the "M1M 96 Modbus Manual V1.3C"
PDF (which uses scaled 32/64-bit integers at 0x5B00..).

Addresses in this YAML:

| Quantity            | Addr | Type          | Source       |
|---------------------|------|---------------|--------------|
| Active power L1     | 102  | float (FP32_R)| L1 of per-phase block; Total at 100 |
| Power factor L1     | 118  | float (FP32_R)| Total at 116 |
| Apparent power L1   | 126  | float (FP32_R)| Total at 124 |
| Voltage L1 (L-N)    | 142  | float (FP32_R)| Avg at 140; line voltage L1-L2 at 134 |
| Current L1          | 150  | float (FP32_R)| Total at 148 |
| Frequency           | 156  | float (FP32_R)| —            |
| Energy imported     | 158  | float (FP32_R)| Wh; multiplied by 0.001 for HA |

Per-phase quantities are laid out [Total, L1, L2, L3] back-to-back (2
registers each, phase stride +2). To add L2 / L3 readings, copy a sensor
and bump the address by 2 or 4.

## Verifying the register map

Sanity-check the addresses on first run:

1. Open HA → Developer Tools → States, search `sensor.abb_m1m_meter_voltage`.
2. Compare to L1 voltage on the meter's front panel.
3. Repeat for current, active power, frequency.

If a reading is wildly off:

- **Reads as `unknown` or hangs** → wrong address, wrong baud/parity, or
  the bus isn't physically working (run `tools/m1m_debug.py --loopback`
  first to rule out the USB-serial path).
- **Reads as a NaN or absurd number (~10³⁸ or denormalised tiny)** →
  byte-order issue. Try `value_type: FP32` instead of `FP32_R`, or set
  `byte_order: little_endian` on the modbus_controller.
- **Reads as zero** → meter may not be measuring on that phase (single-
  phase wired into a 3-phase config slot), or the register is for a
  phase that doesn't exist in your wiring configuration.

## Home Assistant Energy dashboard

The kWh sensors already carry `device_class: energy` + `unit: kWh` +
`state_class: total_increasing`, which is what the Energy dashboard
requires.

Settings → Dashboards → Energy → Electricity grid:

- **Add consumption:** `sensor.abb_m1m_meter_energy_imported`
- **Return to grid** (only if you export, e.g. solar):
  `sensor.abb_m1m_meter_energy_exported`

Data backfills within ~1 hour.

## Tuning

- `poll_interval` (in `substitutions:`) — default 10 s. Don't go below
  ~2 s at 19200 baud or the bus starves.
- `send_wait_time` (in `common/modbus-rtu.yaml`, currently 200 ms) — drop
  to 50 ms once stable.
- For bus runs > 50 m with CRC errors, drop baud to 9600 (in both the
  YAML and on the meter).

## References

- ABB *M1M 96 Modbus Manual V1.3C* — §4.2 Energy, §4.3 Real Time Data
- ESPHome modbus_controller: <https://esphome.io/components/modbus_controller.html>
- HA Energy dashboard: <https://www.home-assistant.io/docs/energy/electricity-grid/>
