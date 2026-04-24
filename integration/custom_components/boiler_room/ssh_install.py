"""SSH-based remote installation of the Boiler Room agent on SteamOS devices."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

# The install script run on the SteamOS device over SSH
INSTALL_COMMANDS = """
set -euo pipefail

INSTALL_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/boiler-room"
SERVICE_DIR="$HOME/.config/systemd/user"
BINARY="boiler-room-agent"
REPO="rappo/boiler-room"

# Download binary
mkdir -p "$INSTALL_DIR"
URL="https://github.com/$REPO/releases/latest/download/${BINARY}-linux-amd64"
if command -v curl &>/dev/null; then
  curl -fsSL "$URL" -o "$INSTALL_DIR/$BINARY"
elif command -v wget &>/dev/null; then
  wget -q "$URL" -O "$INSTALL_DIR/$BINARY"
fi
chmod +x "$INSTALL_DIR/$BINARY"

# Default config
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  HOSTNAME=$(hostname)
  cat > "$CONFIG_DIR/config.yaml" << INNEREOF
device_name: "$HOSTNAME"
api_port: 9451
log_level: info
INNEREOF
fi

# Systemd service
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/boiler-room.service" << 'INNEREOF'
[Unit]
Description=Boiler Room - Home Assistant bridge for SteamOS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/boiler-room-agent
Restart=on-failure
RestartSec=5
Environment=HOME=%h
Environment=XDG_RUNTIME_DIR=/run/user/%U

[Install]
WantedBy=default.target
INNEREOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now boiler-room
loginctl enable-linger "$(whoami)" 2>/dev/null || true

echo "BOILER_ROOM_INSTALLED_OK"
""".strip()


async def install_via_ssh(
    host: str,
    username: str = "deck",
    password: str | None = None,
    key_filename: str | None = None,
    port: int = 22,
) -> dict[str, Any]:
    """Install the Boiler Room agent on a remote SteamOS device via SSH.

    Uses asyncssh for non-blocking SSH operations.

    Returns:
        dict with 'success' (bool), 'message' (str), and 'output' (str)
    """
    try:
        import asyncssh
    except ImportError:
        return {
            "success": False,
            "message": "asyncssh is not installed. Add it to your HA environment.",
            "output": "",
        }

    connect_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "username": username,
        "known_hosts": None,  # Accept new hosts during first-time setup
    }

    if key_filename:
        connect_kwargs["client_keys"] = [key_filename]
    elif password:
        connect_kwargs["password"] = password

    try:
        _LOGGER.info("Connecting to %s@%s:%d via SSH...", username, host, port)
        async with asyncssh.connect(**connect_kwargs) as conn:
            _LOGGER.info("Connected. Running install script...")
            result = await asyncio.wait_for(
                conn.run(f"bash -c '{INSTALL_COMMANDS}'", check=False),
                timeout=120,  # 2 minute timeout for download + install
            )

            output = (result.stdout or "") + (result.stderr or "")
            success = "BOILER_ROOM_INSTALLED_OK" in output

            if success:
                _LOGGER.info("Agent installed successfully on %s", host)
                return {
                    "success": True,
                    "message": "Boiler Room agent installed and running!",
                    "output": output,
                }
            else:
                _LOGGER.error("Install script failed. Output: %s", output)
                return {
                    "success": False,
                    "message": f"Install script failed (exit code {result.exit_status})",
                    "output": output,
                }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "SSH install timed out after 120 seconds",
            "output": "",
        }
    except Exception as err:
        _LOGGER.exception("SSH install failed")
        return {
            "success": False,
            "message": f"SSH connection failed: {err}",
            "output": "",
        }


async def check_agent_status(host: str, username: str = "deck",
                              password: str | None = None,
                              port: int = 22) -> dict[str, Any]:
    """Check if the Boiler Room agent is running on a remote device."""
    try:
        import asyncssh
    except ImportError:
        return {"installed": False, "running": False}

    connect_kwargs: dict[str, Any] = {
        "host": host, "port": port, "username": username,
        "known_hosts": None,
    }
    if password:
        connect_kwargs["password"] = password

    try:
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(
                "systemctl --user is-active boiler-room 2>/dev/null && "
                "echo AGENT_ACTIVE || echo AGENT_INACTIVE",
                check=False,
            )
            output = result.stdout or ""
            return {
                "installed": "AGENT_ACTIVE" in output or "AGENT_INACTIVE" in output,
                "running": "AGENT_ACTIVE" in output,
            }
    except Exception:
        return {"installed": False, "running": False}
