# ESP32 Garage Door Sensor

An ESP32 that reports whether the garage door is open or closed to Home Assistant, and can open/close it by pulsing the opener's button through a relay.

- Reed switch on `GPIO23` (to GND, internal pull-up; HIGH = door open)
- Relay module on `GPIO13` (active-LOW, 300 ms pulse = one button press)

## Versions

I started with the C++ Arduino sketch, then wrote ESPHome and MicroPython versions to see what they'd be like. All three do the same job:

| Version | Files | Talks to Home Assistant via |
| --- | --- | --- |
| C++ (Arduino) | `esp32_door_sensor.ino`, `secrets.example.h` | MQTT + discovery |
| ESPHome | `garage-door.yaml` | Native API |
| MicroPython | `main.py`, `secrets.example.py` | MQTT + discovery |

> **If this is ever used again, use the ESPHome version.** It's the least code, gets OTA updates and a fallback hotspot for free, and doesn't need reconnect or discovery logic maintained by hand.

## Example setup (ESPHome)

Create `secrets.yaml` next to `garage-door.yaml`:

```yaml
wifi_ssid: "YourNetwork"
wifi_password: "YourWifiPassword"

# Generate with: openssl rand -base64 32   (or let the ESPHome dashboard create one)
garage_door__encryption_key: "REPLACE_WITH_32_BYTE_BASE64_KEY"
```

Then flash it over USB (later updates can go over Wi-Fi):

```bash
esphome run garage-door.yaml
```

Home Assistant should discover the device automatically; add it with the same `garage_door__encryption_key`.

### Other versions

- **C++:** copy `secrets.example.h` to `secrets.h`, fill it in, and build with the Arduino IDE or `arduino-cli` (ESP32 core + `PubSubClient`).
- **MicroPython:** copy `secrets.example.py` to `secrets.py`, fill it in, and upload both files with `mpremote cp main.py secrets.py :`.
