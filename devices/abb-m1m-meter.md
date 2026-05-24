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

- Modbus address:  1   (matches `modbus_address` in the YAML)
- Baud:            19200
- Parity:          NONE
- Stop bits:       1

If yours differs, edit `substitutions:` in `abb-m1m-meter.yaml`.

## Flashing

```bash
cd <repo>
cp secrets.yaml.example secrets.yaml          # first time only
$EDITOR secrets.yaml
esphome run devices/abb-m1m-meter.yaml
```

After the first USB flash, updates go OTA over WiFi.

## Verifying the register map

The Modbus manual that ships with the M1M 15/20/30 family doesn't formally
list the M1M 12, so sanity-check the addresses on first run:

1. Open HA → Developer Tools → States, search `sensor.abb_m1m_meter_voltage`.
2. Compare to L1 voltage on the meter's front panel.
3. Repeat for current and active power.

If a reading is wildly off:

- **Off by a power of 10** → fix the `multiply` filter (wrong resolution).
- **Reads as `unknown` or hangs** → wrong address or wrong baud/parity.
- **Reads as a huge number** → byte/word order swap. Try `U_DWORD_R` /
  `S_DWORD_R` value types, or look up the M1M 12 legacy register map and
  patch the addresses.

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
