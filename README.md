# Boiler Room

Home Assistant integration for SteamOS. Launch games and apps, play Jellyfin media, control power and volume, and watch temperatures and disk use on a Steam Deck or SteamOS PC, by voice through Assist or from the dashboard.

Two parts:

- **`boiler-room-agent`**, a Go binary running on the SteamOS device. It scans the Steam library and Flatpak apps, reads system sensors, launches things, and serves a REST API with a WebSocket for power-state events.
- **`boiler_room`**, a Home Assistant custom integration. It finds agents over mDNS, polls the API, creates the entities below, and registers the voice sentences with Assist itself.

Requires Home Assistant 2026.10 or newer. Jellyfin is optional.

## Install

### 1. The agent, on the SteamOS device

```bash
ssh deck@<device-ip>
curl -fsSL https://raw.githubusercontent.com/rappo/boiler-room/main/install.sh | bash
```

The installer downloads the latest release to `~/.local/bin/boiler-room-agent`, writes `~/.config/boiler-room/config.yaml`, and starts a systemd user service (`boiler-room`) that also runs at boot before anyone logs in. It ends with the API address, which you can open in a browser: `http://<device-ip>:9451/api/v1/status`.

### 2. The integration, in Home Assistant

HACS: add `https://github.com/rappo/boiler-room` as a custom repository (type Integration), install Boiler Room, restart Home Assistant. Without HACS, copy `custom_components/boiler_room/` into your config's `custom_components/` and restart.

Needs Home Assistant 2026.10.0 or newer: that release added the integration-provided LLM tools this integration ships (`llm.py`), with the tool annotations that mark the power actions destructive and the status ones read-only.

Then **Settings → Devices & services → Add integration → Boiler Room**. A device on the same network is discovered and offered; otherwise enter its IP. The confirm step shows the device name and how many games and apps it found.

Voice commands work as soon as the device is added. There is nothing to import or create.

### 3. Options

**Settings → Devices & services → Boiler Room → Configure**:

| Option | Purpose |
|---|---|
| Voice nicknames | Names the device answers to in sentences, comma-separated. Blank means the device name plus `deck`, `steam machine`, `gaming pc`. |
| Jellyfin server URL, API key | Enables the Jellyfin sentences and services. The key comes from Jellyfin Dashboard → API Keys; the connection is checked before saving. |
| Jellyfin client app | Flatpak ID of the player on the device. Default `org.jellyfin.JellyfinDesktop`. |
| YouTube client app | Flatpak ID for YouTube searches. Blank uses the device's browser. |
| Cache artists / albums, refresh interval | Caches library names for phonetic voice matching (see Jellyfin below). |
| App aliases | Voice names for Flatpak apps, `name=flatpak.id`, one per line or comma-separated. |

## What you get

One device per agent, with these entities:

| Entity | Type | Notes |
|---|---|---|
| `media_player.<device>` | media player | Current game or app, volume, turn off; the media browser lists games and apps to launch |
| Current Activity | sensor | Running game or app, or `Idle` |
| Power State | sensor | `on`, `sleep`, `shutdown`, `reboot`; pushed over the WebSocket, kept across HA restarts |
| CPU, GPU, Ambient Temperature | sensor | As the device reports them |
| Battery | sensor | Only on devices that report one (Steam Deck) |
| Disk Usage | sensor | Root filesystem use |
| Home Directory Size | sensor | Size of `/home/deck`, measured hourly |
| Installed Games | sensor | Count |
| Game Library, App Library | sensor | Counts, with the full name lists as attributes |
| Steam Account | sensor | Logged-in Steam account |
| Quick Launch | select | Pick a game or app to launch |
| Volume | number | 0 to 100 |
| Gaming Mode | switch | On is Game Mode, off is Desktop Mode |
| Suspend, Shutdown, Reboot | button | |
| Restart & Lock Steam | button | Returns to the Steam user picker |
| Wake (WoL) | button | Wake-on-LAN; the MAC is stored, so it works while the device is off and unreachable |

## Voice commands

Every command is a Home Assistant intent (`BoilerRoomLaunchGame`, `BoilerRoomPower`, ...; the full list is under [Intents and tools](#intents-and-tools)). Two lanes reach them:

- **Exact sentences, every pipeline, instantly.** The tables below are registered as a conversation trigger, the mechanism HA automations use. An Assist pipeline checks sentence triggers before it hands the text to its conversation agent, so these work offline with the Home Assistant agent and with any LLM agent, with no model call.
- **Free phrasing, with an LLM conversation agent.** A pipeline whose agent (Ollama, OpenAI, Anthropic, Google, ...) has the *Assist* API enabled gets one tool per intent, with descriptions that say when to use which. "Can you put something from the Criterion collection on the deck" or "what is the Steam machine doing right now" then work without a matching sentence, and the agent can ask about the status or the recent launches, which have no sentences at all. With the [MCP Server](https://www.home-assistant.io/integrations/mcp_server/) integration the same tools reach external MCP clients.

Say the sentences to any Assist endpoint: a voice satellite, the companion app, or the Assist text box. `<device>` is any of the device's voice nicknames. With one device you can leave it out ("Launch Balatro", "Set volume to 30"). With several, name one ("Launch Balatro on the living room pc"); a sentence without a device, or a nickname two devices share, makes Assist ask which one you mean. The sentences are the core phrasings only; an LLM agent covers the rest.

### System

| Sentence | Does |
|---|---|
| `Wake up / Turn on / Power on the <device>` | Wake-on-LAN |
| `Suspend / Sleep the <device>` · `Put the <device> to sleep` | Suspend |
| `Turn off / Shut down / Power off the <device>` | Shut down |
| `Reboot / Restart the <device>` | Reboot |
| `Set the <device> volume to 50` · `Volume 50 on the <device>` · `Set volume to 50` | Volume 0 to 100 |

### Games and apps

| Sentence | Does |
|---|---|
| `Launch / Play / Start / Open / Run / Boot up / Fire up <game>` · `Put on <game>` | Fuzzy-matches the installed Steam games and launches the best one. Aliases work: "bg3", "cyberpunk", "red dead", "civ". |
| `Play <game> on the <device>` | Same, on a named device |
| `Launch / Start / Open the <app> app` | Launches a Flatpak app; your app aliases are checked first |
| `Open the <app> app on the <device>` | Same, on a named device |

A game name that matches nothing is tried as an app, and the other way around.

### Jellyfin

Needs the Jellyfin URL and API key in options. "Jelly Fin", "Jellyfish" and "jelly fin" are accepted, since that is what speech-to-text tends to produce.

| Sentence | Does |
|---|---|
| `Play / Watch / Listen to / Put on <query> on Jellyfin` | Searches and plays the top result |
| `Play the movie / show / series / album / song <query> on Jellyfin` | Same, limited to that type |
| `Show me / Browse / Look up <query> on Jellyfin` | Opens the item's page without playing |
| `Show / Find the movie / show / album / artist <query> on Jellyfin` | Same, with a type |
| `Pause / Resume / Unpause / Stop Jellyfin` | Playback control (`playback` and `the stream` also work) |
| `Rewind / Go back / Skip back Jellyfin` · `Fast forward / Skip forward / Skip ahead Jellyfin` | Seek |
| `Search YouTube for <query>` · `Open / Play / Watch <query> on YouTube` | Opens a YouTube search in the configured client |

The Jellyfin app is launched if it is not running. With caching on, artist and album names are matched phonetically, so "dead mouse" finds deadmau5 and "gorillas" finds Gorillaz.

### Intents and tools

Each action is one intent; an LLM agent sees it as the tool `boiler_room__<intent>`, and `conversation.process`, scripts and the `/api/intent/handle` endpoint can call it by intent name. Every one takes an optional `device` slot (nickname, device name or entry title). Without it, an action that changes one device goes to the only device or asks which one; the Jellyfin actions pick the device with Jellyfin configured; the read-only ones report on every device.

| Intent | Slots | Tool annotations |
|---|---|---|
| `BoilerRoomLaunchGame` | `name` | |
| `BoilerRoomLaunchApp` | `name` | |
| `BoilerRoomJellyfinPlay` | `query`, optional `type`: Movie, Series, Episode, Audio, MusicAlbum | |
| `BoilerRoomJellyfinBrowse` | `query`, optional `type`: those plus MusicArtist, Person | |
| `BoilerRoomJellyfinControl` | `action`: pause, unpause, stop, rewind, fastforward | idempotent |
| `BoilerRoomYoutubeSearch` | `query` | |
| `BoilerRoomPower` | `action`: suspend, shutdown, reboot | destructive |
| `BoilerRoomWake` | | idempotent |
| `BoilerRoomSetVolume` | `level` 0 to 100 | idempotent |
| `BoilerRoomGetStatus` | | read-only |
| `BoilerRoomListRecent` | | read-only |

### Services

Everything above is also a service, for automations and scripts. Each takes the same fields plus the optional `device`; without it the first reachable device is used (services never ask). All return `speech`, usable with `set_conversation_response`, and the read-only ones return their facts as well.

| Service | Fields |
|---|---|
| `boiler_room.launch_game` | `name` |
| `boiler_room.launch_app` | `name` |
| `boiler_room.jellyfin_play` | `query`, optional `type` |
| `boiler_room.jellyfin_browse` | `query`, optional `type` |
| `boiler_room.jellyfin_control` | `action` |
| `boiler_room.youtube_search` | `query` |
| `boiler_room.power` | `action` |
| `boiler_room.wake` | |
| `boiler_room.set_volume` | `level` |
| `boiler_room.get_status` | |
| `boiler_room.list_recent` | |

## The agent

```bash
systemctl --user status boiler-room
journalctl --user -u boiler-room -f
systemctl --user restart boiler-room
```

`~/.config/boiler-room/config.yaml`:

```yaml
device_name: "steamdeck"      # name shown in Home Assistant and used as a voice nickname
api_port: 9451
log_level: "info"             # debug, info, warn, error
preferred_browser: "firefox"  # for YouTube when no client app is set: firefox, chrome, or a Flatpak ID
repo_url: ""                  # GitHub repo URL; enables update checks on release builds
```

Jellyfin needs nothing on the agent side; the integration talks to the Jellyfin server directly and only asks the agent to launch the app.

Every request is logged in the journal except fast, successful GETs. Power actions try Steam's D-Bus, then `loginctl`, then logind over D-Bus, and only then `sudo systemctl`, so the sudoers rule the installer offers is a fallback, not a requirement.

### API

Base URL `http://<device-ip>:9451/api/v1`.

| Endpoint | Method | Returns or does |
|---|---|---|
| `/status` | GET | Version, power state, current app, device name and ID, MAC, counts |
| `/games`, `/apps`, `/shortcuts` | GET | Installed Steam games, Flatpak apps, non-Steam shortcuts; `?refresh=true` rescans |
| `/games/{appid}/artwork/{type}` | GET | Artwork: grid, hero, icon, logo |
| `/recent` | GET | Recently launched games and apps |
| `/launch` | POST | Launch a game, app or URL |
| `/system/sensors` | GET | Temperatures, battery, disk, home size, volume |
| `/system/volume` | POST | Set volume or mute |
| `/system/power` | POST | suspend, shutdown, reboot, restart_steam |
| `/system/session` | POST | Switch to gaming or desktop mode |
| `/system/users` | GET | Steam accounts on the device and which is logged in |
| `/system/users/switch` | POST | Log in as another account |
| `/plugins`, `/plugins/{name}/action` | GET, POST | Registered plugins and their actions |
| `/update/check`, `/update/apply` | GET, POST | Self-update against the newest GitHub release (release builds with `repo_url` only) |
| `/ws` | WebSocket | Power-state events, with a server ping every 30 s |

`/health` at the root (no `/api/v1`) answers `ok`, a plain liveness probe.

A WebSocket event looks like `{"type": "power_state_changed", "timestamp": 1716566400, "data": {"power_state": "sleep"}}`. The integration applies it to the Power State sensor at once, which is what makes "turn the TV off when the device sleeps" automations prompt.

## Troubleshooting

**A sentence is not recognized.** Check the device is loaded under Settings → Devices & services. If the sentence names the device, the word must be one of its voice nicknames. Settings → Voice assistants → Assist → Debug shows which trigger a sentence would match without running it. Debug logging for `custom_components.boiler_room` shows the registered sentences and which intent each command reached. Phrasings outside the tables need a pipeline with an LLM conversation agent.

**An LLM agent does not know about the device.** The agent's *Control Home Assistant* (Assist API) option must be on; the tools are listed under Settings → Voice assistants → the agent's debug view as `boiler_room__...`. A device must be loaded: the tools exist only while one is.

**Assist answers twice.** Versions before 2026.10.29.1 had a "Create Voice Automations" button that wrote three automations (`Boiler Room | System Controls`, `Boiler Room | Games & Apps`, `Boiler Room | Jellyfin Media`). The integration now answers those sentences itself, so delete the three automations and any blueprints you imported for them.

**Jellyfin says there is no active player session.** The Jellyfin app on the device is not running and could not be started. Install it: `flatpak install org.jellyfin.JellyfinDesktop`.

**A game is not found.** Say more of the name. `journalctl --user -u boiler-room -f` on the device shows what the agent was asked to launch.

## Development

See [AGENTS.md](AGENTS.md) for the layout, the two test layers, and how to run them.

## License

MIT
