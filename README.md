# 🔥 Boiler Room

> Home Assistant integration for SteamOS — voice-control your games and media on any SteamOS device.

**Boiler Room** bridges [Home Assistant](https://www.home-assistant.io/) and [SteamOS](https://store.steampowered.com/steamos), letting you launch games, control media, and manage your SteamOS device with voice commands, automations, and physical buttons.

Named after the engine room where steam is made — and inspired by the [Aeolipile](https://en.wikipedia.org/wiki/Aeolipile), the world's first steam-powered device, built by Hero of Alexandria.

## Features

- 🎮 **Launch games by voice** — "Play Elden Ring" via Home Assistant Assist
- 📚 **Browse your game library** — Games appear in HA's Media Browser with metadata
- 🔍 **Auto-discovery** — Agent advertises via mDNS, HA finds it automatically
- 🎯 **Zero config** — Game libraries are auto-detected, no manual path editing
- 💾 **Survives everything** — Lives in `/home/deck/`, persists across reboots and OS updates
- 🏗️ **No root required** — User-level systemd service, no immutable FS issues
- 🌡️ **System monitoring** — CPU/GPU temps, battery level, volume control
- ⏻ **Power control** — Suspend, shutdown, reboot from HA

## Architecture

Two components that snap together:

1. **`boiler-room-agent`** — A Go binary that runs on SteamOS, scans your games, and exposes a REST API
2. **`boiler_room` HACS integration** — A Home Assistant integration that discovers agents and creates media_player entities

## Installation

### Step 1: Install the agent on SteamOS

SSH into your SteamOS device and run the installer:

```bash
ssh deck@<your-deck-ip>
curl -fsSL https://raw.githubusercontent.com/rappo/boiler-room/main/install.sh | bash
```

The installer will:
- Download the agent binary to `~/.local/bin/`
- Create a default config at `~/.config/boiler-room/config.yaml`
- Set up and start a systemd user service
- Enable auto-start at boot (even before GUI login)

You should see output like:
```
✅ Boiler Room is running!

  API:      http://192.168.1.54:9451/api/v1/status
  Config:   /home/deck/.config/boiler-room/config.yaml
  Service:  systemctl --user status boiler-room
```

### Step 2: Add the integration in Home Assistant

1. Copy `integration/custom_components/boiler_room/` to your HA config's `custom_components/` directory (or install via HACS when available)
2. Restart Home Assistant
3. Go to **Settings → Devices & Services → Add Integration**
4. Search for **Boiler Room**
5. If your Deck is on the same network, it may be auto-discovered. Otherwise, enter the device IP address.
6. Confirm the device — you'll see your game count and device name
7. Done! 🎉

### What you get in HA

- **Media Player** entity — shows current game, play/pause/stop controls
- **Quick Launch** selector — pick a game from your library to launch
- **Sensors** — CPU/GPU temperature, current game, installed game count
- **Buttons** — Reboot, Shutdown, Suspend
- **Volume** slider

## Managing the Agent

```bash
# Check agent status
systemctl --user status boiler-room

# View logs
journalctl --user -u boiler-room -f

# Restart the agent
systemctl --user restart boiler-room

# Edit configuration
nano ~/.config/boiler-room/config.yaml
```

## Status

🚧 **Early development** — Phase 1 (game scanning + launching + voice commands)

## License

MIT
