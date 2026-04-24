"""Constants for the Boiler Room integration."""

DOMAIN = "boiler_room"
DEFAULT_PORT = 9451

CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_ID = "device_id"

# Platforms to set up
PLATFORMS = ["media_player", "sensor", "number", "button", "select"]

# mDNS service type
ZEROCONF_TYPE = "_boiler-room._tcp.local."

# Update interval (seconds)
SCAN_INTERVAL = 30
