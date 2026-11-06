# MicroPython port of the ESP32 garage door controller.
#
# Same behaviour and MQTT topics as the Arduino sketch, so Home Assistant
# doesn't notice the swap:
#   garage/door/state   retained OPEN / CLOSED
#   garage/door/status  retained online / offline (LWT)
#   garage/door/set     OPEN / CLOSE commands
#   homeassistant/cover/garage_door/config   retained discovery payload
#
# Needs umqtt.simple (bundled with the standard ESP32 firmware; otherwise
# `mpremote mip install umqtt.simple`).

import time
import network
import machine
import ubinascii
from machine import Pin
from umqtt.simple import MQTTClient

import secrets  # see secrets.example.py

REED_PIN = 23
RELAY_PIN = 13

WIFI_RETRY_MS = 10_000
MQTT_RETRY_MS = 5_000
MQTT_PING_MS = 30_000        # umqtt.simple doesn't send keepalives itself
RELAY_PULSE_MS = 300
REED_DEBOUNCE_MS = 75

# Reboot if the main loop stalls (e.g. a hung socket). Set False while
# developing at the REPL; once started, the watchdog can't be stopped.
USE_WATCHDOG = True
WATCHDOG_MS = 30_000

TOPIC_STATE = b"garage/door/state"
TOPIC_STATUS = b"garage/door/status"
TOPIC_CMD = b"garage/door/set"
DISCOVERY_TOPIC = b"homeassistant/cover/garage_door/config"

DISCOVERY_PAYLOAD = (
    b'{"name":"Garage Door",'
    b'"unique_id":"esp32_garage_cover_01",'
    b'"device_class":"garage",'
    b'"command_topic":"garage/door/set",'
    b'"state_topic":"garage/door/state",'
    b'"payload_open":"OPEN","payload_close":"CLOSE",'
    b'"state_open":"OPEN","state_closed":"CLOSED",'
    b'"optimistic":false,'
    b'"availability_topic":"garage/door/status",'
    b'"availability_mode":"latest",'
    b'"payload_available":"online","payload_not_available":"offline",'
    b'"device":{"identifiers":["esp32_garage_01"],'
    b'"name":"ESP32 Garage Controller",'
    b'"manufacturer":"DIY","model":"ESP32 Relay Controller"}}'
)

OPEN = b"OPEN"
CLOSED = b"CLOSED"


def state_from_reed(raw):
    # Pull-up: HIGH = switch open = door OPEN
    return OPEN if raw else CLOSED


class GarageController:
    def __init__(self):
        self.reed = Pin(REED_PIN, Pin.IN, Pin.PULL_UP)
        # Active-LOW relay: start HIGH (released) with no glitch at boot
        self.relay = Pin(RELAY_PIN, Pin.OUT, value=1)

        now = time.ticks_ms()

        raw = self.reed.value()
        self.stable_reed = raw
        self.last_raw_reed = raw
        self.last_reed_change = now
        self.door_state = state_from_reed(raw)

        self.pulse_active = False
        self.pulse_start = 0

        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.wifi_was_connected = False
        self._wifi_connect()
        self.last_wifi_attempt = now

        client_id = b"esp32-garage-" + ubinascii.hexlify(machine.unique_id())
        self.mqtt = MQTTClient(
            client_id,
            secrets.MQTT_SERVER,
            port=getattr(secrets, "MQTT_PORT", 1883),
            user=getattr(secrets, "MQTT_USER", None),
            password=getattr(secrets, "MQTT_PASSWORD", None),
            keepalive=60,
        )
        self.mqtt.set_callback(self.on_message)
        self.mqtt.set_last_will(TOPIC_STATUS, b"offline", retain=True, qos=1)
        self.mqtt_connected = False
        self.last_mqtt_attempt = time.ticks_add(now, -MQTT_RETRY_MS)  # try right away
        self.last_ping = now

        print("Ready")

    # ---------------- Wi-Fi / MQTT ----------------

    def _wifi_connect(self):
        try:
            self.wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
        except OSError as e:
            print("WiFi connect error:", e)

    def _drop_mqtt(self):
        # Close the socket without sending DISCONNECT, so the broker
        # publishes our "offline" last will, as PubSubClient effectively does.
        self.mqtt_connected = False
        try:
            self.mqtt.sock.close()
        except Exception:
            pass

    def _connect_mqtt(self):
        print("MQTT connecting...")
        try:
            self.mqtt.connect()
            self.mqtt_connected = True
            print("MQTT Connected")
            self.mqtt.publish(TOPIC_STATUS, b"online", retain=True)
            self.mqtt.subscribe(TOPIC_CMD)
            self.mqtt.publish(DISCOVERY_TOPIC, DISCOVERY_PAYLOAD, retain=True)
            self.last_ping = time.ticks_ms()
            self.publish_state()
        except OSError as e:
            print("MQTT Failed:", e)
            self._drop_mqtt()

    def service_network(self, now):
        if not self.wlan.isconnected():
            if self.wifi_was_connected:
                self.wifi_was_connected = False
                print("WiFi disconnected")
                self._drop_mqtt()
            if time.ticks_diff(now, self.last_wifi_attempt) >= WIFI_RETRY_MS:
                self.last_wifi_attempt = now
                print("WiFi reconnect attempt...")
                self._wifi_connect()
            return

        if not self.wifi_was_connected:
            self.wifi_was_connected = True
            print("WiFi Connected", self.wlan.ifconfig()[0])

        if not self.mqtt_connected:
            if time.ticks_diff(now, self.last_mqtt_attempt) >= MQTT_RETRY_MS:
                self.last_mqtt_attempt = now
                self._connect_mqtt()
            return

        try:
            self.mqtt.check_msg()  # non-blocking; calls on_message
            if time.ticks_diff(now, self.last_ping) >= MQTT_PING_MS:
                self.mqtt.ping()
                self.last_ping = now
        except OSError as e:
            print("MQTT connection lost:", e)
            self._drop_mqtt()

    def publish_state(self):
        print("STATE:", self.door_state.decode())
        if not self.mqtt_connected:
            return
        try:
            self.mqtt.publish(TOPIC_STATE, self.door_state, retain=True)
        except OSError as e:
            print("State publish failed:", e)
            self._drop_mqtt()

    def on_message(self, topic, msg):
        if topic != TOPIC_CMD:
            return
        cmd = msg[:15]
        print("MQTT Command:", cmd)

        if cmd == b"OPEN":
            wanted = OPEN
        elif cmd == b"CLOSE":
            wanted = CLOSED
        else:
            print("Ignored command: unsupported payload")
            return

        if wanted == self.door_state:
            print("Ignored command: door already in requested state")
            return

        self.trigger_pulse()

    # ---------------- Relay ----------------

    def trigger_pulse(self):
        if self.pulse_active:
            print("Relay pulse ignored: already active")
            return
        self.pulse_active = True
        self.pulse_start = time.ticks_ms()
        self.relay.value(0)
        print("Relay pulse started")

    def service_relay(self, now):
        if self.pulse_active and time.ticks_diff(now, self.pulse_start) >= RELAY_PULSE_MS:
            self.pulse_active = False
            self.relay.value(1)
            print("Relay pulse ended")

    # ---------------- Reed switch ----------------

    def service_reed(self, now):
        raw = self.reed.value()
        if raw != self.last_raw_reed:
            self.last_raw_reed = raw
            self.last_reed_change = now

        if raw != self.stable_reed and time.ticks_diff(now, self.last_reed_change) >= REED_DEBOUNCE_MS:
            self.stable_reed = raw
            previous = self.door_state
            self.door_state = state_from_reed(raw)
            if previous != self.door_state:
                self.publish_state()

    # ---------------- Main loop ----------------

    def run(self):
        wdt = machine.WDT(timeout=WATCHDOG_MS) if USE_WATCHDOG else None
        while True:
            if wdt:
                wdt.feed()
            now = time.ticks_ms()
            self.service_network(now)
            self.service_relay(now)
            self.service_reed(now)
            time.sleep_ms(5)


GarageController().run()
