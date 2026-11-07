"""Constants for the Boiler Room integration."""

DOMAIN = "boiler_room"
DEFAULT_PORT = 9451

CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_ID = "device_id"

# Platforms to set up
PLATFORMS = ["media_player", "sensor", "number", "button", "select", "switch"]

# mDNS service type
ZEROCONF_TYPE = "_boiler-room._tcp.local."

# Update interval (seconds)
SCAN_INTERVAL = 15

# Options: the media player the remote's volume buttons control. Unset, the
# buttons only fire boiler_room_remote_button events.
CONF_VOLUME_BUTTONS_ENTITY = "volume_buttons_entity"

# HA event fired for every remote button event the agent pushes.
EVENT_REMOTE_BUTTON = f"{DOMAIN}_remote_button"

# Options: comma-separated names a device answers to in voice commands.
CONF_DEVICE_NICKNAMES = "device_nicknames"
