# Hot water tank temperature

ESP8266 reads one or more DS18B20 one-wire probes on a hot water tank, detects when the
tank is heating (via an LDR on the panel's indicator lamp), shows the top temperature on
a small OLED, and publishes to Home Assistant.

## Bill of materials

- Wemos D1 mini (ESP8266)
- Waterproof DS18B20 probe (stainless tube) — one now, a second later
- One 4.7 kΩ resistor (the one-wire bus pull-up — required, see wiring)
- GME12864-11/12/13 V3.2 OLED — 128×64 I2C, SSD1306 controller, address 0x3C
- LDR / photoresistor (e.g. GL5528) + one 10 kΩ resistor (R_b) for the heating
  indicator — have 4.7 kΩ / 47 kΩ on hand for tuning
- 5 V supply for the D1 mini

## Install plan (two phases)

- **Now — top probe:** a DS18B20 replacing the mechanical temperature dial at the
  **top** of the tank. It sits against the **external tank metal**, not in the water.
- **Later — bottom probe:** a second DS18B20 mounted **inside** the tank near the
  bottom (where the thermocouple sits), once the heater's lower section is opened up.
  Its sensor block in `hot-water-tank.yaml` is present but commented out.

### Measurement caveat (read this before trusting the number)

The top probe measures the **outer tank wall**, not the water. It reads **lower than,
and lags behind, the actual water temperature** — the wall warms up slowly after the
element fires and stays cooler than the water inside. Treat it as a relative/trend
signal, not an absolute water temperature, until the internal bottom probe is added.

## Wiring

```
   Wemos D1 mini                         DS18B20
   ─────────────                         ───────
        3V3 ───────────┬───────────────  VDD (red)
                       │
                      [4.7 kΩ]            (pull-up: DATA ↔ 3V3)
                       │
   D2 / GPIO4  ─────────┴───────────────  DATA (yellow)
        GND ──────────────────────────── GND (black)

   Wemos D1 mini                         GME12864 OLED (I2C)
   ─────────────                         ───────────────────
        3V3 ───────────────────────────  VCC
        GND ───────────────────────────  GND
   D6 / GPIO12 ───────────────────────── SDA
   D5 / GPIO14 ───────────────────────── SCL

   Wemos D1 mini                         LDR (heating indicator)
   ─────────────                         ───────────────────────
        3V3 ──────────────── LDR ────────┐   (LDR in a dark tunnel on the lamp)
                                          │
         A0 ──────────────────────────────┤   (tap point)
                                          │
                                       [10 kΩ]  R_b
                                          │
        GND ──────────────────────────────┘
```

- The 4.7 kΩ pull-up between DATA and 3V3 is **mandatory** — without it the bus
  floats and no sensor is found.
- All probes share the same three lines (VDD / DATA / GND) on one bus; the second
  probe just taps the same wires.
- GPIO4 (D2) is used because it has no boot-strapping role and doesn't conflict with
  the built-in LED on GPIO2. The UART pins stay free, so logs work over USB without
  the `logger: baud_rate: 0` workaround the meter node needs.
- The OLED is on I2C at **D6/D5 (GPIO12/GPIO14)** — *not* the usual D2/D1, because
  GPIO4 is already the one-wire pin. GPIO0/2/15 are avoided for I2C: their
  boot-strapping levels clash with the bus idling high through its pull-ups. The
  GME12864 module has its own on-board SDA/SCL pull-ups, so no extra resistors.
- The OLED shows the top probe temperature (see Display below). If the image is
  shifted or garbled, the module is the SH1106 variant — change `model:` to
  `"SH1106 128x64"` in the YAML.
- The **LDR divider** taps **A0**. On the Wemos D1 mini, A0 has an on-board 220k/100k
  divider, so the header pin is **0–3.3 V tolerant** — a plain LDR + R_b divider off
  3V3 is safe (no voltage-capping resistor needed, unlike a bare ESP-01/ESP8285). More
  light → lower LDR resistance → higher voltage. See "Heating indicator (LDR)" below.

## Display

The OLED shows the top probe temperature right-aligned (e.g. `21.2°C`) with a static
🌡️ thermometer icon on the left (`-- °C` until the first reading lands). When the LDR
detects the panel lamp lit (i.e. the tank is heating), a 🔥 fire icon appears in the
**top-right corner**.

The temperature font is `gfonts://Roboto`; the icons come from the Material Design Icons
webfont — both are downloaded at compile time, so the first `esphome compile`/`run`
needs internet. (The SSD1306 is monochrome: the on-screen color is whatever the physical
panel emits and isn't software-controllable.)

## Heating indicator (LDR)

Detects when the tank is heating by reading the existing 220 VAC indicator lamp with an
LDR — **no galvanic connection to mains**. The LDR feeds the A0 divider (see Wiring);
ESPHome smooths it (EMA) and an `analog_threshold` binary sensor (`Heating`, with
hysteresis + debounce) reports ON/OFF to Home Assistant and drives the OLED fire icon.

### Dark tunnel (this is what rejects ambient light — ~90% mechanical)

- Cover the LDR body/leads with **black heat-shrink**, leaving only the sensing face.
- Extend a short black tube (heat-shrink or a 3D-printed black PETG hood) ~5–10 mm past
  the face to form a tunnel; press it onto the indicator lens.
- **Seal the rim** against the lens with black silicone or a black EVA-foam gasket — any
  leaked ambient light enters here. Add a hot-glue strain relief on the cable.
- Avoid PLA / plain tape (panel heat); use silicone / heat-shrink / PETG.

### Choosing R_b (10 kΩ default)

Pick R_b near the LDR's resistance at the ON/OFF boundary (max sensitivity when
`R_b ≈ R_ldr` there): **4.7 kΩ** if the lamp drives the LDR very bright (few kΩ),
**10 kΩ** general, **47 kΩ** if the lamp is dim / the LDR stays high-ohm. Keep
R_b ≤ ~47 kΩ so it doesn't interact with A0's ~320 kΩ on-board input impedance.

### Tuning the thresholds

1. Flash, then `esphome logs` and watch `sensor.hot_water_tank_heater_indicator_ldr`
   (`heater_ldr`, 200 ms, 3 decimals) with the tunnel mounted. Values are in A0
   chip-scale units (0–1.0 V).
2. **Lamp OFF**, vary room light (lamps, sun) → record the **max dark** value.
3. **Lamp ON** → record the **min on** value.
4. Want a clear gap (> 0.2, ratio > 3×). Set `ldr_threshold_off` just above max-dark and
   `ldr_threshold_on` just below min-on (the gap between them is the hysteresis band).
   These are `substitutions:` in the YAML.
5. **Wrong-resistor signs:** ON ≈ OFF (tiny gap) → R_b far from R_ldr, change family
   (brighter → 4.7 kΩ, dimmer → 47 kΩ); reads high even when OFF → ambient leaking, fix
   the tunnel seal; reads ~0 even when ON → R_b too small, raise it.

## Flashing & bring-up

```bash
cd <repo>
cp secrets.yaml.example secrets.yaml          # first time only
$EDITOR secrets.yaml

# 1. Validate
esphome config devices/hot-water-tank.yaml

# 2. First flash over USB, then watch the logs for the discovered ROM address
esphome run devices/hot-water-tank.yaml
#    look for the "Found devices:" / "0x...." line in the boot log
```

The ROM address is printed **only once, during boot** (in `dump_config`, the `[C]`
lines), e.g.:

```
[C][gpio.one_wire:087]:   Found devices:
[C][gpio.one_wire:090]:     0x3156d9d446a61328 (DS18B20)
```

`esphome run` attaches the serial monitor right after the reset, so this line has often
already scrolled past by the time you're watching. **You must reset the board while the
logs are being captured.** The reliable way: open a log stream first, then reset the
board (press the **RST** button on the D1 mini, or replug USB) so `dump_config` prints
with the monitor already listening:

```bash
esphome logs devices/hot-water-tank.yaml    # then press RST on the board
```

Copy the printed address into the top probe's `address:` field in
`hot-water-tank.yaml` and uncomment it, then re-flash (OTA over WiFi now works):

```bash
esphome run devices/hot-water-tank.yaml
```

Pinning the address keeps each probe's identity stable. **Once the bottom probe is
added, both sensors must have an explicit `address:`** — with more than one device on
the bus, an un-addressed `dallas_temp` sensor is ambiguous and the config will not
validate.

## Verifying in Home Assistant

1. Confirm `sensor.hot_water_tank_tank_top_temperature` appears.
2. It should sit near room/ambient when the heater is idle and rise after the element
   fires (slowly, since it's reading the wall).
3. Quick sanity check: warm the probe by hand and watch the value climb.

The `filter_out: 85.0` in the YAML suppresses the DS18B20's transient power-on reset
reading (it reports exactly 85.0 °C on a failed/incomplete conversion).

## Tuning

- `poll_interval` (in `substitutions:`) — set to 2 s for a responsive display. A tank
  changes slowly, so raise it (e.g. 10–30 s) if you want to cut bus/log traffic.
- `resolution: 12` gives 0.0625 °C steps with a ~750 ms conversion. Drop to 10 or 9
  for faster conversions if you ever put many sensors on the bus.

## References

- ESPHome one-wire bus: <https://esphome.io/components/one_wire.html>
- ESPHome Dallas/DS18B20 sensor: <https://esphome.io/components/sensor/dallas_temp.html>
