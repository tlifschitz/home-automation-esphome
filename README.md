# home-automation-esphome

ESPHome configurations for the custom nodes on my home network.

## Layout

```
.
├── common/                Reusable YAML packages shared by all devices
│   ├── base.yaml          WiFi, API, OTA, logger, captive portal, diagnostics
│   └── modbus-rtu.yaml    UART + Modbus RTU stack for RS485 devices
├── devices/               One file per physical node
│   ├── abb-m1m-meter.yaml ABB M1M power meter via Modbus RTU
│   ├── abb-m1m-meter.md   Wiring & setup notes for that node
│   ├── hot-water-tank.yaml DS18B20 temp + LDR heating detect + OLED
│   └── hot-water-tank.md  Wiring & setup notes for that node
├── tools/                 Bench utilities (run on laptop, not ESP)
│   ├── m1m_debug.py       Read M1M registers via USB-RS485 for verification
│   ├── requirements.txt
│   └── README.md
├── secrets.yaml.example   Template; copy to secrets.yaml and fill in
├── secrets.yaml           (gitignored) WiFi creds, API/OTA passwords
└── .gitignore
```

## Adding a new device

1. Create `devices/<node-name>.yaml`.
2. At the top, declare `substitutions:` for at least `device_name` and
   `friendly_name`.
3. Add a `packages:` block pulling in `common/base.yaml` and any other
   relevant common packages.
4. Add the device-specific config (board, sensors, etc.).
5. Flash with `esphome run devices/<node-name>.yaml`.

See `devices/abb-m1m-meter.yaml` for a worked example.

## First-time setup on a new machine

```bash
git clone <this-repo>
cd home-automation-esphome
cp secrets.yaml.example secrets.yaml
$EDITOR secrets.yaml    # fill in real values
pip install esphome
esphome run devices/abb-m1m-meter.yaml
```

The `secrets.yaml` file is gitignored — never commit credentials.

## Running from the Home Assistant ESPHome add-on

If you'd rather use the HA add-on UI, clone this repo into
`/config/esphome/` on the HA host. The add-on auto-discovers any
`devices/*.yaml` file.
