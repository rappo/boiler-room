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

## Architecture

Two components that snap together:

1. **`boiler-room-agent`** — A Go binary that runs on SteamOS, scans your games, and exposes a REST API
2. **`boiler_room` HACS integration** — A Home Assistant integration that discovers agents and creates media_player entities

## Quick Start

### SteamOS (one command)

```bash
curl -fsSL https://raw.githubusercontent.com/rappo/boiler-room/main/install.sh | bash
```

### Home Assistant

1. Install via HACS (or copy `integration/custom_components/boiler_room/` to your HA config)
2. The agent is auto-discovered — click "Configure" when prompted
3. Say "Play [game name]" 🎉

## Status

🚧 **Early development** — Phase 1 (game scanning + launching + voice commands)

## License

MIT
