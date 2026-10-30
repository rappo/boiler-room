# Boiler Room

> Home Assistant integration for SteamOS — voice-control your games, media, and system from anywhere.

**Boiler Room** bridges [Home Assistant](https://www.home-assistant.io/) and [SteamOS](https://store.steampowered.com/steamos), letting you launch games, play Jellyfin media, switch between desktop and gaming mode, and manage your SteamOS device with voice commands, automations, and dashboard controls.


## Architecture

Two components that snap together:

1. **`boiler-room-agent`** — A Go binary that runs on your SteamOS device. It scans your game library, monitors system sensors, and exposes a REST API for control.
2. **`boiler_room` integration** — A Home Assistant custom integration that discovers agents on the network and creates entities for games, media, sensors, and power controls.

```
Voice / HA Dashboard
        |
  Home Assistant
        |
  Boiler Room Integration (Python)
        |  HTTP REST + WebSocket
  Boiler Room Agent (Go, on SteamOS)
        |
  Steam / Flatpak / steamosctl / Jellyfin API
```

## Features

### Games and Apps
- Launch any Steam game by voice or from the HA dashboard
- Launch Flatpak apps (Firefox, Jellyfin, etc.) the same way
- Fuzzy matching — handles partial names, abbreviations, and aliases
- Built-in aliases for common games (e.g., "bg3" = Baldur's Gate 3)
- Recent launches tracked and persisted across reboots

### Jellyfin Integration
- Search and play movies, shows, music, and albums by voice
- Type hints to disambiguate ("play the movie Fargo" vs "play the show Fargo")
- Browse content without playing — navigates to the item's page in the Jellyfin app
- Auto-launches the Jellyfin app if not running, skips re-launch if already open
- Configured entirely from the HA UI (Settings > Integrations > Configure)
- Independent of the official Jellyfin integration — no entity sprawl

### System Control
- Suspend, shutdown, reboot via voice or buttons
- Wake-on-LAN — works even when the device is off (MAC address persisted)
- Real-time power state tracking via WebSocket (on, sleep, shutdown, reboot)
- Gaming/Desktop mode toggle switch
- Volume control by voice or slider

### Monitoring
- CPU and GPU temperature sensors
- Battery level and charging status
- Current game detection
- Installed game and app counts

### Discovery
- mDNS auto-discovery — HA finds your device automatically
- Supports multiple SteamOS devices on the same network

## Example Usage

All voice commands work through Home Assistant Assist (voice satellites, the app, or the Assist text box).

### Launch games

```
"Launch Elden Ring"
"Play Vampire Survivors"
"Start Balatro on the steam machine"
"Fire up Cyberpunk"
"Put on Stardew Valley"
```

Aliases work too:

```
"Play bg3"          → Baldur's Gate 3
"Launch cyberpunk"  → Cyberpunk 2077
"Play red dead"     → Red Dead Redemption 2
"Start civ"         → Sid Meier's Civilization VI
```

### Launch apps

```
"Open Firefox on the deck"
"Launch the Jellyfin app"
"Start the Chrome app"
```

### Jellyfin — play media

```
"Play Robocop on Jellyfin"
"Watch Breaking Bad on Jellyfin"
"Listen to Dark Side of the Moon on Jellyfin"
```

With type hints (when names collide):

```
"Play the movie Fargo on Jellyfin"
"Play the show Fargo on Jellyfin"
"Play the album Fargo on Jellyfin"
"Listen to the song Bohemian Rhapsody on Jellyfin"
```

### Jellyfin — browse without playing

```
"Show me Taskmaster on Jellyfin"
"Browse Akira Kurosawa on Jellyfin"
"Look up the show Breaking Bad on Jellyfin"
"Show me the album Abbey Road on Jellyfin"
```

This navigates to the item's page in the Jellyfin app without starting playback.

### System control

```
"Suspend the steam machine"
"Put the deck to sleep"
"Shut down the gaming pc"
"Reboot the steam machine"
"Set deck volume to 50"
```

### YouTube

```
"Search YouTube for cat videos"
"Play lo-fi beats on YouTube"
```

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
Boiler Room is running!

  API:      http://<device-ip>:9451/api/v1/status
  Config:   /home/deck/.config/boiler-room/config.yaml
  Service:  systemctl --user status boiler-room
```

### Step 2: Add the integration in Home Assistant

1. Copy `custom_components/boiler_room/` to your HA config's `custom_components/` directory (or install it through HACS)
2. Restart Home Assistant
3. Go to **Settings > Devices & Services > Add Integration**
4. Search for **Boiler Room**
5. If your device is on the same network, it may be auto-discovered. Otherwise, enter the IP address.
6. Confirm the device — you'll see your game count and device name

Voice commands work as soon as the device is added: the integration registers its sentences with Assist itself (see [Voice Commands](#voice-commands)).

### Step 3: Configure Jellyfin (optional)

1. Go to **Settings > Integrations > Boiler Room > Configure**
2. Enter your Jellyfin server URL (e.g., `http://<jellyfin-ip>:8096`)
3. Enter your Jellyfin API key (generate one in Jellyfin Dashboard > API Keys)
4. Submit — the connection is validated before saving

### What you get in HA

| Entity | Type | Description |
|---|---|---|
| Media Player | `media_player` | Shows current game, play/pause/stop controls |
| Quick Launch | `select` | Dropdown to pick and launch a game |
| Gaming Mode | `switch` | Toggle between gaming mode and desktop mode |
| Wake (WoL) | `button` | Wake the device via Wake-on-LAN (always available) |
| Suspend | `button` | Suspend the device |
| Shutdown | `button` | Shut down the device |
| Reboot | `button` | Reboot the device |
| Power State | `sensor` | Real-time power state (on, sleep, shutdown, reboot) |
| CPU Temperature | `sensor` | Current CPU temperature |
| GPU Temperature | `sensor` | Current GPU temperature |
| Battery Level | `sensor` | Battery percentage |
| Volume | `number` | Volume slider (0-100) |
| Current Game | `sensor` | Name of the running game |

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

### Agent configuration

Located at `~/.config/boiler-room/config.yaml`:

```yaml
device_name: "steamdeck"       # Name shown in Home Assistant
api_port: 9451                 # API port (default: 9451)
log_level: "info"              # Log level: debug, info, warn, error
preferred_browser: "firefox"   # Browser for YouTube: firefox, chrome, or Flatpak ID
repo_url: ""                   # Forgejo/GitHub repo URL for self-updates
```

Jellyfin configuration is managed entirely from the HA UI — no agent-side config needed.

## API Reference

The agent exposes a REST API at `http://<device-ip>:9451/api/v1/`.

| Endpoint | Method | Description |
|---|---|---|
| `/status` | GET | Device info, game counts, mode, MAC address |
| `/games` | GET | List installed Steam games |
| `/games?refresh=true` | GET | Re-scan and list games |
| `/apps` | GET | List installed Flatpak apps |
| `/shortcuts` | GET | List non-Steam shortcuts |
| `/launch` | POST | Launch a game, app, or URL |
| `/recent` | GET | Recently launched games and apps |
| `/games/{appid}/artwork/{type}` | GET | Game artwork (grid, hero, icon, logo) |
| `/system/sensors` | GET | CPU/GPU temp, battery, volume |
| `/system/volume` | POST | Set volume level or mute |
| `/system/power` | POST | Suspend, shutdown, or reboot |
| `/system/session` | POST | Switch between desktop and gaming mode |
| `/plugins` | GET | List registered plugins |
| `/plugins/{name}/action` | POST | Execute a plugin action |
| `/update/check` | GET | Check for agent updates |
| `/update/apply` | POST | Apply a pending update |
| `/ws` | WebSocket | Real-time state events (see below) |
| `/health` | GET | Health check |

### WebSocket Events

Connect to `/api/v1/ws` for real-time push events. The agent sends server-side pings every 30 seconds to keep the connection alive.

**`power_state_changed`** — fires when the system power state changes (via any method: voice, Steam menu, power button, HDMI-CEC remote, etc.)

```json
{
  "type": "power_state_changed",
  "timestamp": 1716566400,
  "data": {
    "power_state": "sleep"
  }
}
```

Power state values:
| Value | Meaning |
|---|---|
| `on` | System is running (also sent on wake from sleep) |
| `sleep` | System is entering suspend |
| `shutdown` | System is shutting down |
| `reboot` | System is rebooting |

The HA integration uses these events to update `sensor.<device>_power_state` instantly, enabling automations that react to power changes without polling delay (e.g., turning off a TV when the device sleeps).

## Voice Commands

Voice commands need **no setup**. When a device is added, the integration registers its sentences with Assist directly (the same conversation-trigger API HA's automations use), so there is no automation to create, no blueprint to import and no sentence file to copy. Say any of the sentences below to a voice satellite, the app, or the Assist text box.

### Device nicknames

Sentences that name the device accept any of its **nicknames**. By default a device answers to its own name (as the agent reports it, e.g. `steamdeck`) plus `deck`, `steam machine` and `gaming pc`. Change them under **Settings → Integrations → Boiler Room → Configure → Voice nicknames** (comma-separated); the sentences update immediately.

With **one device**, sentences without a device name ("Launch Balatro", "Set volume to 30") target it. With **two or more devices**, say the nickname ("Launch Balatro on the living room pc"); a nickname shared by several devices, or a sentence with no device, makes Assist ask which one you mean. Give each device a distinct nickname to avoid the question.

### System controls

| Sentence | What it does |
|---|---|
| `Wake up / Turn on / Power on the <device>` | Sends a Wake-on-LAN magic packet |
| `Suspend / Sleep the <device>` · `Put the <device> to sleep` | Suspends the device |
| `Turn off / Shut down / Power off the <device>` | Shuts down the device |
| `Reboot / Restart the <device>` | Reboots the device |
| `Set the <device> volume to 50` · `Volume 50 on the <device>` · `Set volume to 50` | Sets volume (0–100) |

### Games and apps

| Sentence | What it does |
|---|---|
| `Launch / Play / Start / Open / Run / Boot up / Fire up <game>` | Fuzzy match and launch (aliases work: "bg3") |
| `Put on <game>` | Same |
| `Play <game> on the <device>` | Same, on a named device |
| `Launch / Start / Open the <app> app` | Launch a Flatpak app (your app aliases are checked first) |
| `Open the <app> app on the <device>` | Same, on a named device |

A game sentence that matches no game falls back to apps, and vice versa.

### Jellyfin media

Jellyfin sentences target the device whose options have Jellyfin configured. `Jelly Fin`, `Jellyfish` and `jelly fin` are accepted spellings for what speech-to-text makes of "Jellyfin".

| Sentence | What it does |
|---|---|
| `Play / Watch / Listen to / Put on <query> on Jellyfin` | Search and play the top result |
| `Play the movie <query> on Jellyfin` | Movie only |
| `Play the show / series <query> on Jellyfin` | Series only |
| `Play the album <query> on Jellyfin` | Album only |
| `Play the song <query> on Jellyfin` | Song only |
| `Show me / Browse / Look up <query> on Jellyfin` | Open the item's page without playing |
| `Show / Find the movie / show / album / artist <query> on Jellyfin` | Same, with a type hint |
| `Pause Jellyfin / playback / the stream` | Pause |
| `Resume / Unpause Jellyfin` | Resume |
| `Stop Jellyfin` | Stop |
| `Rewind / Go back / Skip back Jellyfin` | Seek backward |
| `Fast forward / Skip forward / Skip ahead Jellyfin` | Seek forward |
| `Search YouTube for <query>` · `Play <query> on YouTube` | Open a YouTube search on the device |

### Upgrading from the automation-based setup

Versions before 2026.10.29.1 shipped a **Create Voice Automations** button that wrote three automations to your `automations.yaml`. Those automations keep working, but now Boiler Room answers the same sentences itself, so each command would run twice and Assist may answer twice. If you pressed that button, delete the three automations named `Boiler Room: System Controls`, `Boiler Room: Games & Apps` and `Boiler Room: Jellyfin Media` (ids `boiler_room_system_controls`, `boiler_room_games_and_apps`, `boiler_room_jellyfin_media`) in **Settings → Automations**, or remove them from `automations.yaml` and reload automations. The blueprints under `blueprints/automation/boiler_room/`, if you imported them, can go too. The button entity itself is removed from the registry on the first start of the new version.

### Services

The same handlers behind the voice commands are exposed as HA services, callable from automations, scripts, or Developer Tools. Every service takes an optional `device` (a nickname, the device name or the entry title); without it the first device that was reached is used.

| Service | Parameters |
|---|---|
| `boiler_room.launch_game` | `name` |
| `boiler_room.launch_app` | `name` |
| `boiler_room.jellyfin_play` | `query`, optional `type` (Movie, Series, Audio, MusicAlbum, Episode) |
| `boiler_room.jellyfin_browse` | `query`, optional `type` |
| `boiler_room.jellyfin_control` | `action` (pause/unpause/stop/rewind/fastforward) |
| `boiler_room.youtube_search` | `query` |
| `boiler_room.power` | `action` (suspend/shutdown/reboot) |
| `boiler_room.wake` | — |
| `boiler_room.set_volume` | `level` (0–100) |

All services return a response with a `speech` key, for `set_conversation_response` in your own automations.

### Jellyfin Phonetic Matching

If Jellyfin voice caching is enabled (Settings → Integrations → Boiler Room → Configure), the integration caches your library and matches voice queries phonetically. This handles artists and albums with unusual spellings that STT engines mangle:

| You say | STT transcribes | Cache matches |
|---|---|---|
| "Play deadmau5" | "dead mouse" | deadmau5 (82%) |
| "Play Nine Inch Noize" | "nine inch noise" | Nine Inch Noize (93%) |
| "Play Gorillaz" | "gorillas" | Gorillaz (88%) |
| "Play Mötley Crüe" | "motley crew" | Mötley Crüe (91%) |

## Troubleshooting

### Voice command not recognized
The sentences are registered when the integration loads, so check that the device shows as loaded under Settings → Integrations and that Assist is using the Home Assistant conversation agent (sentence triggers only fire there, not inside an LLM agent that is set to never use HA intents). Enable debug logging for `custom_components.boiler_room` to see "Registered N voice sentences" and, per command, which handler a sentence was routed to. If a sentence names a device, the word you use must be one of its voice nicknames (Configure → Voice nicknames).

### Assist answers twice
You still have the automations the old **Create Voice Automations** button created. Delete them; see [Upgrading from the automation-based setup](#upgrading-from-the-automation-based-setup).

### WoL button is disabled
The WoL button should always be available. If it's disabled, restart HA — this was fixed in v0.5.0 by decoupling the WoL button from the coordinator.

### Jellyfin says "no active player session"
The Jellyfin app needs to be running on the SteamOS device. The integration will auto-launch it, but if the app crashes or isn't installed, you'll see this error. Install Jellyfin Desktop via Flatpak: `flatpak install org.jellyfin.JellyfinDesktop`.

### Game not found
Try saying the full name. Partial matches work but can be ambiguous. Check `journalctl --user -u boiler-room -f` on the SteamOS device to see what the agent received.

## License

MIT

---

*Built with [Opus](https://www.anthropic.com/claude)*
