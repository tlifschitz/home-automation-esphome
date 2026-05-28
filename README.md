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

## Continuous integration

`.github/workflows/esphome-config.yaml` runs on every push to `main` and
on pull requests. Three jobs gate each other:

```
list-devices  →  validate (matrix: every devices/*.yaml)
              →  build    (matrix: every devices/*.yaml; needs validate)
```

- **list-devices** discovers `devices/*.yaml` (`ls | jq`) and exposes the
  list as a JSON output. Adding a new device file is enough, no workflow
  edits.
- **validate** runs `esphome config <file>` in the official
  `ghcr.io/esphome/esphome:stable` container (schema + substitution
  check).
- **build** runs `esphome compile <file>`, but only if every `validate`
  matrix job passed, so a broken YAML doesn't burn minutes compiling.

A CI-only `common/secrets.yaml` stub is written at the start of each job;
real credentials stay on your machine.

### Caching

Two caches keep warm runs fast (≈1 min total vs ≈3 min cold):

- **PlatformIO toolchains** `/github/home/.platformio` (~234 MB).
  Shared across devices; key includes a hash of every `devices/*.yaml`
  and `common/*.yaml`, with a restore-key fallback so the cache is
  warm on almost every run.
- **ESPHome per-device state** `devices/.esphome/build/<name>/`
  *plus* `storage/<name>.yaml.json`, `storage/<name>.yaml.validated.yaml`,
  and `idedata/<name>.json`. Per-device key keyed on the device file
  and `common/*.yaml`, so editing one node doesn't bust the other
  node's incremental state.

Two non-obvious requirements that took finding:

- Inside a container job GitHub overrides `$HOME=/github/home`, so
  PlatformIO writes to `/github/home/.platformio`, **not** the image
  default `/root/.platformio`. Caching the wrong path silently caches
  nothing useful.
- ESPHome keeps per-device state files (`storage/*.json`, `idedata/*.json`)
  **outside the per-device build dir**. Without them in the cache,
  ESPHome sees "core config or version changed" on every run, deletes
  `.pioenvs`, and throws away whatever the cache action just restored.
  Including those files is what lets SCons's incremental compilation
  actually work end-to-end.
