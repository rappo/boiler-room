# Boiler Room

> Home Assistant integration for SteamOS — voice-control your games, media, and system from anywhere.

**Boiler Room** bridges [Home Assistant](https://www.home-assistant.io/) and [SteamOS](https://store.steampowered.com/steamos), letting you launch games, play Jellyfin media, switch between desktop and gaming mode, and manage your SteamOS device with voice commands, automations, and dashboard controls.

Named after the engine room where steam is made — inspired by the [Aeolipile](https://en.wikipedia.org/wiki/Aeolipile), the world's first steam-powered device.

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
        |  HTTP REST
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

1. Copy `integration/custom_components/boiler_room/` to your HA config's `custom_components/` directory
2. Copy `integration/custom_components/boiler_room/custom_sentences/en/boiler_room.yaml` to `<HA config>/custom_sentences/en/boiler_room.yaml`
3. Restart Home Assistant
4. Go to **Settings > Devices & Services > Add Integration**
5. Search for **Boiler Room**
6. If your device is on the same network, it may be auto-discovered. Otherwise, enter the IP address.
7. Confirm the device — you'll see your game count and device name

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
| `/ws` | WebSocket | Real-time state events |
| `/health` | GET | Health check |

## Voice Command Reference

All voice commands are registered as [custom intents](https://www.home-assistant.io/docs/intent_script/) via `custom_sentences/en/boiler_room.yaml`. They work through HA Assist (voice satellites, the app, or the Assist text box).

> **Note:** Sentence patterns use HA's template syntax: `(A|B)` = either word, `{slot}` = free-form input. Device aliases like `deck`, `steam machine`, `tv`, `living room`, and `gaming pc` are interchangeable.

| Intent | Sentence Pattern | What It Does |
|---|---|---|
| **BoilerRoomLaunchGame** | `Launch {game}` | Launches a Steam game or Flatpak app by name. Supports fuzzy matching and aliases (e.g., "bg3" → Baldur's Gate 3). |
| | `Play/Start/Open/Run/Boot up/Fire up {game}` | |
| | `Put on {game}` | |
| | `Launch {game} on the deck/steam machine` | Target a specific device by alias. |
| **BoilerRoomOpenApp** | `Open {app} on the deck/steam machine` | Opens a Flatpak app, falls back to game matching. |
| | `Launch/Start the {app} app` | |
| **BoilerRoomJellyfinSearch** | `Play {query} on Jellyfin` | Searches Jellyfin and plays the top result. Auto-launches the Jellyfin app if needed. |
| | `Watch/Listen to/Put on {query} on Jellyfin` | |
| | `Play the movie {query} on Jellyfin` | With type hint — disambiguates when names collide. |
| | `Play the show/series {query} on Jellyfin` | |
| | `Play the album {query} on Jellyfin` | |
| | `Play the song {query} on Jellyfin` | |
| **BoilerRoomJellyfinBrowse** | `Show me {query} on Jellyfin` | Navigates to the item's page without playing. |
| | `Browse/Look up {query} on Jellyfin` | |
| | `Show the movie {query} on Jellyfin` | With type hint. |
| | `Show the show/series {query} on Jellyfin` | |
| | `Show the album/artist/band {query} on Jellyfin` | |
| **BoilerRoomYouTubeSearch** | `Search YouTube for {query}` | Opens a YouTube search or plays a video on the device. |
| | `Play/Watch {query} on YouTube` | |
| **BoilerRoomSystemControl** | `Suspend/Sleep the deck/steam machine` | Suspends the device. |
| | `Put the deck/steam machine to sleep` | |
| | `Turn off/Shut down/Power off the deck` | Shuts down the device. |
| | `Reboot/Restart the deck/steam machine` | Reboots the device. |
| | `Set deck volume to {number}` | Sets volume (0–100). |

### Jellyfin phonetic matching

If Jellyfin voice caching is enabled (Settings → Integrations → Boiler Room → Configure), the integration caches your Jellyfin library and matches voice queries phonetically. This handles artists and albums with unusual spellings that STT engines mangle:

| You say | STT transcribes | Cache matches |
|---|---|---|
| "Play deadmau5" | "dead mouse" | deadmau5 (82%) |
| "Play Nine Inch Noize" | "nine inch noise" | Nine Inch Noize (93%) |
| "Play Gorillaz" | "gorillas" | Gorillaz (88%) |
| "Play Mötley Crüe" | "motley crew" | Mötley Crüe (91%) |

## Troubleshooting

### Voice command returns "Sorry, I am not aware of any area called ..."
The speech-to-text engine transcribed a word differently than expected. Check the STT output in the pipeline debug view and add the alternate spelling to `custom_sentences/en/boiler_room.yaml`.

### WoL button is disabled
The WoL button should always be available. If it's disabled, restart HA — this was fixed in v0.5.0 by decoupling the WoL button from the coordinator.

### Jellyfin says "no active player session"
The Jellyfin app needs to be running on the SteamOS device. The integration will auto-launch it, but if the app crashes or isn't installed, you'll see this error. Install Jellyfin Desktop via Flatpak: `flatpak install org.jellyfin.JellyfinDesktop`.

### Game not found
Try saying the full name. Partial matches work but can be ambiguous. Check `journalctl --user -u boiler-room -f` on the SteamOS device to see what the agent received.

### Custom sentences not loading
The `boiler_room.yaml` file must be at `<HA config>/custom_sentences/en/boiler_room.yaml`, not inside the integration directory. After copying, restart HA.

## License

MIT
