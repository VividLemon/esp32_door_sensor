# ESP32 Garage Door Sensor

Reports whether the garage door is open or closed to Home Assistant, and opens/closes it by pulsing the opener's button through a relay.

## Use the YAML

If you come across this, use **`garage-door.yaml`**.

1. In Home Assistant, open **ESPHome Device Builder** and create a new device (board: **Generic ESP32 Board**).
2. Replace its config with the contents of `garage-door.yaml`.
3. In the Builder's **Secrets** editor, add:

   ```yaml
   wifi_ssid: "YourNetwork"
   wifi_password: "YourWifiPassword"
   garage_door__encryption_key: "REPLACE_WITH_32_BYTE_BASE64_KEY" # openssl rand -base64 32
   ```

4. **Install**. The first flash is over USB; updates after that go over Wi-Fi.

Wiring: reed switch on `GPIO23` (to GND), relay on `GPIO13` (active-LOW).

## Other files

`esp32_door_sensor.ino` (C++) and `main.py` (MicroPython) are earlier experiments that do the same thing over MQTT. I started with C++, then tried ESPHome and Python to compare.
