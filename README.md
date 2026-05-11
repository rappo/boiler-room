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

## Voice Commands

Voice commands work through **HA automations** backed by **Boiler Room services**. The integration ships 3 pre-built automations you can create with one button press — fully editable in the HA UI.

### Quick Setup

**Option A: One-click** — Press the **"Create Voice Automations"** button on your Boiler Room device page. This writes 3 automations to your `automations.yaml` and reloads — they appear instantly in Settings → Automations, fully editable.

**Option B: Copy-paste** — Create automations manually using the YAML below. Go to Settings → Automations → Create Automation → ⋮ → Edit in YAML, paste, and save.

<details>
<summary><strong>System Controls</strong> — wake, suspend, shutdown, reboot, volume</summary>

```yaml
alias: "Boiler Room: System Controls"
description: "Voice commands for SteamOS device power and volume control."
mode: single
triggers:
  - trigger: conversation
    command:
      - "(Wake up|Turn on|Power on) the (deck|steam machine|gaming pc)"
    id: wake
  - trigger: conversation
    command:
      - "(Suspend|Sleep) the (deck|steam machine|gaming pc)"
      - "Put the (deck|steam machine|gaming pc) to sleep"
    id: suspend
  - trigger: conversation
    command:
      - "(Turn off|Shut down|Shutdown|Power off) the (deck|steam machine|gaming pc)"
    id: shutdown
  - trigger: conversation
    command:
      - "(Reboot|Restart) the (deck|steam machine|gaming pc)"
    id: reboot
  - trigger: conversation
    command:
      - "(Set|Change) (the|) (deck|steam machine|gaming pc) volume to {volume}"
      - "Volume {volume} (on|) (the|) (deck|steam machine|gaming pc)"
    id: volume
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: wake
        sequence:
          - action: boiler_room.wake
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: suspend
        sequence:
          - action: boiler_room.power
            data:
              action: suspend
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: shutdown
        sequence:
          - action: boiler_room.power
            data:
              action: shutdown
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: reboot
        sequence:
          - action: boiler_room.power
            data:
              action: reboot
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: volume
        sequence:
          - action: boiler_room.set_volume
            data:
              level: "{{ trigger.slots.volume | int(50) }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
```

</details>

<details>
<summary><strong>Games & Apps</strong> — launch games and Flatpak apps by voice</summary>

```yaml
alias: "Boiler Room: Games & Apps"
description: "Voice commands for launching Steam games and apps on your SteamOS device."
mode: single
triggers:
  - trigger: conversation
    command:
      - "(Launch|Play|Start|Open|Run|Boot up|Fire up) {game_name}"
      - "Put on {game_name}"
      - "(Launch|Play|Start|Open|Run) {game_name} on the (deck|steam machine|tv|living room|gaming pc)"
    id: launch_game
  - trigger: conversation
    command:
      - "Open {app_name} on the (deck|steam machine|tv|living room|gaming pc)"
      - "(Launch|Start) the {app_name} app"
    id: launch_app
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: launch_game
        sequence:
          - action: boiler_room.launch_game
            data:
              name: "{{ trigger.slots.game_name }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: launch_app
        sequence:
          - action: boiler_room.launch_app
            data:
              name: "{{ trigger.slots.app_name }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
```

</details>

<details>
<summary><strong>Jellyfin Media</strong> — play, browse, control playback, YouTube</summary>

```yaml
alias: "Boiler Room: Jellyfin Media"
description: "Voice commands for Jellyfin media playback, browsing, and YouTube."
mode: single
triggers:
  - trigger: conversation
    command:
      - "(Play|Watch|Listen to|Put on) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_play
  - trigger: conversation
    command:
      - "(Play|Watch|Put on) the movie {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_play_movie
  - trigger: conversation
    command:
      - "(Play|Watch|Put on) the (show|series|tv show) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_play_series
  - trigger: conversation
    command:
      - "(Play|Listen to|Put on) the album {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_play_album
  - trigger: conversation
    command:
      - "(Play|Listen to|Put on) the song {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_play_song
  - trigger: conversation
    command:
      - "(Show me|Browse|Look up) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
      - "(Show|Browse|Find|Look up|Go to) the movie {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
      - "(Show|Browse|Find|Look up|Go to) the (show|series|tv show) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
      - "(Show|Browse|Find|Look up|Go to) the (album|artist|band) {query} (on|in) (Jellyfin|Jelly Fin|Jellyfish|jelly fin)"
    id: jellyfin_browse
  - trigger: conversation
    command:
      - "(Pause|Resume|Unpause) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"
    id: jellyfin_pause
  - trigger: conversation
    command:
      - "(Stop) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"
    id: jellyfin_stop
  - trigger: conversation
    command:
      - "(Rewind|Go back|Skip back) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"
    id: jellyfin_rewind
  - trigger: conversation
    command:
      - "(Fast forward|Skip forward|Skip ahead) (Jellyfin|Jelly Fin|Jellyfish|jelly fin|the stream|playback)"
    id: jellyfin_ff
  - trigger: conversation
    command:
      - "Search YouTube for {query}"
      - "(Open|Play|Watch) {query} on YouTube"
    id: youtube
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: jellyfin_play
        sequence:
          - action: boiler_room.jellyfin_play
            data:
              query: "{{ trigger.slots.query }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_play_movie
        sequence:
          - action: boiler_room.jellyfin_play
            data:
              query: "{{ trigger.slots.query }}"
              type: Movie
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_play_series
        sequence:
          - action: boiler_room.jellyfin_play
            data:
              query: "{{ trigger.slots.query }}"
              type: Series
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_play_album
        sequence:
          - action: boiler_room.jellyfin_play
            data:
              query: "{{ trigger.slots.query }}"
              type: MusicAlbum
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_play_song
        sequence:
          - action: boiler_room.jellyfin_play
            data:
              query: "{{ trigger.slots.query }}"
              type: Audio
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_browse
        sequence:
          - action: boiler_room.jellyfin_browse
            data:
              query: "{{ trigger.slots.query }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_pause
        sequence:
          - action: boiler_room.jellyfin_control
            data:
              action: pause
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_stop
        sequence:
          - action: boiler_room.jellyfin_control
            data:
              action: stop
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_rewind
        sequence:
          - action: boiler_room.jellyfin_control
            data:
              action: rewind
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: jellyfin_ff
        sequence:
          - action: boiler_room.jellyfin_control
            data:
              action: fastforward
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
      - conditions:
          - condition: trigger
            id: youtube
        sequence:
          - action: boiler_room.youtube_search
            data:
              query: "{{ trigger.slots.query }}"
            response_variable: result
          - set_conversation_response: "{{ result.speech | default("Command sent.") }}"
```

</details>

### Available Voice Commands

#### System Controls

| Sentence | What It Does |
|---|---|
| `Wake up the steam machine` | Sends Wake-on-LAN magic packet |
| `Suspend / Sleep the deck` | Suspends the device |
| `Put the steam machine to sleep` | Suspends the device |
| `Turn off / Shut down the deck` | Shuts down the device |
| `Reboot / Restart the steam machine` | Reboots the device |
| `Set volume to 50` | Sets volume (0–100) |

#### Games & Apps

| Sentence | What It Does |
|---|---|
| `Launch Baldur's Gate 3` | Fuzzy match + launch game |
| `Play / Start / Open / Run / Boot up {name}` | Aliases work too (e.g., "bg3") |
| `Launch {name} on the deck` | Target a specific device |
| `Open YouTube on the deck` | Launch a Flatpak app (checks aliases first) |
| `Launch the Firefox app` | Launch by app name |

#### Jellyfin Media

| Sentence | What It Does |
|---|---|
| `Play {query} on Jellyfin` | Search + play top result |
| `Play the movie Fargo on Jellyfin` | With type hint to disambiguate |
| `Play the show / series {query} on Jellyfin` | Series-specific search |
| `Play the album {query} on Jellyfin` | Album-specific search |
| `Play the song {query} on Jellyfin` | Song-specific search |
| `Show me {query} on Jellyfin` | Navigate to item (no playback) |
| `Pause / Resume Jellyfin` | Toggle playback |
| `Stop Jellyfin` | Stop playback |
| `Rewind / Skip back` | Seek backward |
| `Fast forward / Skip ahead` | Seek forward |
| `Search YouTube for {query}` | Open YouTube search on device |
| `Play {query} on YouTube` | Open YouTube with query |

> **Device aliases:** `deck`, `steam machine`, `tv`, `living room`, and `gaming pc` are interchangeable in all commands. Edit the automation to add your own.

### Services

All voice logic is exposed as standard HA services, callable from automations, scripts, or Developer Tools:

| Service | Parameters |
|---|---|
| `boiler_room.launch_game` | `name`, optional `device` |
| `boiler_room.launch_app` | `name`, optional `device` |
| `boiler_room.jellyfin_play` | `query`, optional `type` |
| `boiler_room.jellyfin_browse` | `query`, optional `type` |
| `boiler_room.jellyfin_control` | `action` (pause/unpause/stop/rewind/fastforward) |
| `boiler_room.youtube_search` | `query`, optional `device` |
| `boiler_room.power` | `action` (suspend/shutdown/reboot) |
| `boiler_room.wake` | optional `device` |
| `boiler_room.set_volume` | `level` (0–100) |

All services return a `speech` response variable for use with `set_conversation_response`.

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
Make sure you imported the blueprint **and** created an automation from it. The blueprint alone doesn't do anything — you need to create an automation that uses it.

### WoL button is disabled
The WoL button should always be available. If it's disabled, restart HA — this was fixed in v0.5.0 by decoupling the WoL button from the coordinator.

### Jellyfin says "no active player session"
The Jellyfin app needs to be running on the SteamOS device. The integration will auto-launch it, but if the app crashes or isn't installed, you'll see this error. Install Jellyfin Desktop via Flatpak: `flatpak install org.jellyfin.JellyfinDesktop`.

### Game not found
Try saying the full name. Partial matches work but can be ambiguous. Check `journalctl --user -u boiler-room -f` on the SteamOS device to see what the agent received.

## License

MIT
