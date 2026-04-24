#!/usr/bin/env bash
# Boiler Room — One-line installer for SteamOS
# Usage: curl -fsSL https://raw.githubusercontent.com/rappo/boiler-room/main/install.sh | bash
set -euo pipefail

VERSION="${BOILER_ROOM_VERSION:-latest}"
INSTALL_DIR="$HOME/.local/bin"
CONFIG_DIR="$HOME/.config/boiler-room"
SERVICE_DIR="$HOME/.config/systemd/user"
BINARY="boiler-room-agent"
REPO_BASE="http://192.168.1.50:3210/rappo/boiler-room"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🔥 Installing Boiler Room...${NC}"
echo ""

# 0. Stop existing service if running (binary can't be overwritten while in use)
if systemctl --user is-active boiler-room &>/dev/null; then
  echo -e "${YELLOW}→ Stopping existing service for upgrade...${NC}"
  systemctl --user stop boiler-room
fi

# 1. Download binary
echo -e "${YELLOW}→ Downloading agent binary...${NC}"
mkdir -p "$INSTALL_DIR"

if [ "$VERSION" = "latest" ]; then
  URL="${REPO_BASE}/releases/download/v0.4.1/${BINARY}-linux-amd64"
else
  URL="${REPO_BASE}/releases/download/v${VERSION}/${BINARY}-linux-amd64"
fi

if command -v curl &>/dev/null; then
  curl -fsSL "$URL" -o "$INSTALL_DIR/$BINARY"
elif command -v wget &>/dev/null; then
  wget -q "$URL" -O "$INSTALL_DIR/$BINARY"
else
  echo -e "${RED}Error: curl or wget required${NC}"
  exit 1
fi

chmod +x "$INSTALL_DIR/$BINARY"
echo -e "${GREEN}  ✓ Binary installed to $INSTALL_DIR/$BINARY${NC}"

# 2. Default config (don't overwrite existing)
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  HOSTNAME=$(hostname 2>/dev/null || cat /etc/hostname 2>/dev/null || uname -n 2>/dev/null || echo "SteamOS Device")
  cat > "$CONFIG_DIR/config.yaml" << EOF
# Boiler Room Agent Configuration
# This name appears in Home Assistant
device_name: "$HOSTNAME"

# Port for the REST API (default: 9451)
api_port: 9451

# Log level: debug, info, warn, error
log_level: info
EOF
  echo -e "${GREEN}  ✓ Config created at $CONFIG_DIR/config.yaml${NC}"
else
  echo -e "${YELLOW}  ⊘ Config already exists, not overwriting${NC}"
fi

# 3. Systemd user service
mkdir -p "$SERVICE_DIR"

# Helper script to ensure sudoers rule survives SteamOS updates.
# /etc/sudoers.d/ can be wiped on major OS updates, but ~/.local/bin/ persists.
cat > "$INSTALL_DIR/boiler-room-ensure-sudoers" << 'SCRIPT'
#!/bin/bash
# Recreates the sudoers rule if missing (e.g., after a SteamOS update).
SUDOERS_FILE="/etc/sudoers.d/boiler-room"
if [ ! -f "$SUDOERS_FILE" ]; then
  USER=$(whoami)
  echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl suspend, /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot" | sudo tee "$SUDOERS_FILE" > /dev/null 2>&1
  sudo chmod 440 "$SUDOERS_FILE" 2>/dev/null
fi
SCRIPT
chmod +x "$INSTALL_DIR/boiler-room-ensure-sudoers"

cat > "$SERVICE_DIR/boiler-room.service" << 'EOF'
[Unit]
Description=Boiler Room - Home Assistant bridge for SteamOS
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Ensure sudoers rule exists (survives SteamOS updates)
ExecStartPre=%h/.local/bin/boiler-room-ensure-sudoers
ExecStart=%h/.local/bin/boiler-room-agent
Restart=on-failure
RestartSec=5
TimeoutStopSec=3
# Ensure Steam's environment is accessible
Environment=HOME=%h
Environment=XDG_RUNTIME_DIR=/run/user/%U
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%U/bus

[Install]
WantedBy=default.target
EOF
echo -e "${GREEN}  ✓ Systemd service created${NC}"

# 4. Enable and start
echo -e "${YELLOW}→ Starting service...${NC}"
systemctl --user daemon-reload
systemctl --user enable --now boiler-room 2>/dev/null || true
echo -e "${GREEN}  ✓ Service enabled and started${NC}"

# 5. Enable linger (start service at boot, before GUI login)
loginctl enable-linger "$(whoami)" 2>/dev/null || true
echo -e "${GREEN}  ✓ Linger enabled (service starts at boot)${NC}"

# 6. Sudoers rule for passwordless power control (optional)
#    In gaming mode, Steam's D-Bus may not be accessible from the agent.
#    This allows suspend/shutdown/reboot without polkit auth prompts.
#    Uses sudo -n to avoid blocking on password prompt.
SUDOERS_FILE="/etc/sudoers.d/boiler-room"
SUDOERS_RULE="$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/systemctl suspend, /usr/bin/systemctl poweroff, /usr/bin/systemctl reboot"
if [ -f "$SUDOERS_FILE" ]; then
  echo -e "${YELLOW}  ⊘ Sudoers rule already exists${NC}"
else
  if echo "$SUDOERS_RULE" | sudo -n tee "$SUDOERS_FILE" > /dev/null 2>&1 && \
     sudo -n chmod 440 "$SUDOERS_FILE" 2>/dev/null; then
    echo -e "${GREEN}  ✓ Passwordless power control enabled${NC}"
  else
    echo -e "${YELLOW}  ⊘ Skipped sudoers rule (no passwordless sudo). Power control may require manual setup.${NC}"
  fi
fi

# 7. Add ~/.local/bin to PATH if not already there
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  echo "" >> "$HOME/.bashrc"
  echo '# Boiler Room agent' >> "$HOME/.bashrc"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  echo -e "${GREEN}  ✓ Added ~/.local/bin to PATH${NC}"
fi

# Done!
echo ""
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}' || echo "unknown")
PORT=$(grep 'api_port' "$CONFIG_DIR/config.yaml" 2>/dev/null | awk '{print $2}' || echo "9451")

echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Boiler Room is running!${NC}"
echo -e ""
echo -e "  ${BLUE}API:${NC}      http://$IP:$PORT/api/v1/status"
echo -e "  ${BLUE}Config:${NC}   $CONFIG_DIR/config.yaml"
echo -e "  ${BLUE}Service:${NC}  systemctl --user status boiler-room"
echo -e ""
echo -e "  Home Assistant will discover this device automatically."
echo -e "  Or add it manually at: ${BLUE}$IP:$PORT${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════${NC}"
