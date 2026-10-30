"""Wake-on-LAN magic packet, framework-free."""

from __future__ import annotations

import socket

WOL_PORT = 9
BROADCAST = "255.255.255.255"


def normalize_mac(mac: str) -> str:
    """Return the 12 hex digits of a MAC, or raise ValueError."""
    digits = mac.replace(":", "").replace("-", "").replace(".", "").strip()
    if len(digits) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    try:
        bytes.fromhex(digits)
    except ValueError as err:
        raise ValueError(f"Invalid MAC address: {mac}") from err
    return digits.lower()


def magic_packet(mac: str) -> bytes:
    """Six 0xFF bytes followed by the MAC sixteen times."""
    return b"\xff" * 6 + bytes.fromhex(normalize_mac(mac)) * 16


def send_magic_packet(mac: str) -> None:
    """Broadcast the magic packet over UDP (blocking; run in an executor)."""
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (BROADCAST, WOL_PORT))
