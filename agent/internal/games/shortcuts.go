package games

import (
	"encoding/binary"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Shortcut represents a Non-Steam game shortcut from shortcuts.vdf.
type Shortcut struct {
	AppID     string `json:"appid"`
	Name      string `json:"name"`
	Exe       string `json:"exe,omitempty"`
	StartDir  string `json:"start_dir,omitempty"`
	Icon      string `json:"icon,omitempty"`
	Tags      string `json:"tags,omitempty"`
	FlatpakID string `json:"flatpak_id,omitempty"` // Extracted from Exe if it's a Flatpak shortcut
}

// ScanShortcuts reads Non-Steam game shortcuts from shortcuts.vdf.
// The file lives at: ~/.steam/steam/userdata/<userid>/config/shortcuts.vdf
// It's a binary VDF format (not the text VDF used elsewhere).
func ScanShortcuts() ([]Shortcut, error) {
	homeDir, err := os.UserHomeDir()
	if err != nil {
		return nil, fmt.Errorf("cannot determine home directory: %w", err)
	}

	// Find userdata directory — there may be multiple Steam user IDs
	userdataDir := filepath.Join(homeDir, ".steam", "steam", "userdata")
	entries, err := os.ReadDir(userdataDir)
	if err != nil {
		// Try alternate location
		userdataDir = filepath.Join(homeDir, ".local", "share", "Steam", "userdata")
		entries, err = os.ReadDir(userdataDir)
		if err != nil {
			return nil, fmt.Errorf("no userdata directory found: %w", err)
		}
	}

	var allShortcuts []Shortcut

	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		vdfPath := filepath.Join(userdataDir, entry.Name(), "config", "shortcuts.vdf")
		shortcuts, err := parseBinaryVDF(vdfPath)
		if err != nil {
			continue // Skip users without shortcuts
		}
		allShortcuts = append(allShortcuts, shortcuts...)
	}

	return allShortcuts, nil
}

// parseBinaryVDF reads Valve's binary VDF format for shortcuts.
// Format:
//
//	0x00 "shortcuts" 0x00
//	  0x00 "0" 0x00          (entry index)
//	    0x01 "AppName" 0x00 <string> 0x00
//	    0x01 "Exe" 0x00 <string> 0x00
//	    ...
//	    0x02 "appid" 0x00 <4-byte int32>
//	  0x08                    (end of entry)
//	0x08                      (end of shortcuts)
//
// Type tags: 0x00 = nested, 0x01 = string, 0x02 = int32
func parseBinaryVDF(path string) ([]Shortcut, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var shortcuts []Shortcut
	r := &vdfReader{data: data, pos: 0}

	// Skip the root container header: 0x00 "shortcuts" 0x00
	if !r.skipByte(0x00) {
		return nil, fmt.Errorf("invalid VDF: expected 0x00 at start")
	}
	r.readString() // "shortcuts"

	// Read entries
	for {
		typeByte, ok := r.peekByte()
		if !ok || typeByte == 0x08 {
			break // End of container
		}

		if typeByte != 0x00 {
			break // Unexpected
		}
		r.pos++ // consume 0x00

		_ = r.readString() // entry index ("0", "1", etc.)

		shortcut := Shortcut{}
		shortcut = readShortcutFields(r, shortcut)

		// Generate a stable appid string if we got a numeric one
		if shortcut.Name != "" {
			if shortcut.AppID == "" || shortcut.AppID == "0" {
				// Generate from name hash for consistency
				shortcut.AppID = fmt.Sprintf("shortcut_%s", sanitizeForID(shortcut.Name))
			}
			// Extract Flatpak ID from exe if present
			// Exe is typically: /usr/bin/flatpak run com.github.iwalton3.jellyfin-media-player
			// or: flatpak run --command=... com.app.ID
			shortcut.FlatpakID = extractFlatpakID(shortcut.Exe)
			shortcuts = append(shortcuts, shortcut)
		}
	}

	return shortcuts, nil
}

// readShortcutFields reads key-value pairs until end-of-object (0x08).
func readShortcutFields(r *vdfReader, s Shortcut) Shortcut {
	for {
		typeByte, ok := r.peekByte()
		if !ok || typeByte == 0x08 {
			if ok {
				r.pos++ // consume 0x08
			}
			break
		}
		r.pos++ // consume type byte

		switch typeByte {
		case 0x01: // String value
			key := r.readString()
			value := r.readString()
			switch strings.ToLower(key) {
			case "appname":
				s.Name = value
			case "exe":
				s.Exe = value
			case "startdir":
				s.StartDir = value
			case "icon":
				s.Icon = value
			}

		case 0x02: // Int32 value
			key := r.readString()
			val := r.readInt32()
			if strings.ToLower(key) == "appid" && val != 0 {
				// Non-Steam shortcut appids can be negative in the VDF
				// Valve uses unsigned representation
				s.AppID = fmt.Sprintf("%d", uint32(val))
			}

		case 0x00: // Nested container (e.g., tags)
			key := r.readString()
			if strings.ToLower(key) == "tags" {
				tags := readTagsContainer(r)
				s.Tags = strings.Join(tags, ", ")
			} else {
				// Skip unknown nested containers
				skipContainer(r)
			}

		default:
			// Unknown type — try to skip gracefully
			return s
		}
	}
	return s
}

// readTagsContainer reads a tags sub-object.
func readTagsContainer(r *vdfReader) []string {
	var tags []string
	for {
		typeByte, ok := r.peekByte()
		if !ok || typeByte == 0x08 {
			if ok {
				r.pos++
			}
			break
		}
		r.pos++

		if typeByte == 0x01 {
			_ = r.readString() // tag index
			tag := r.readString()
			if tag != "" {
				tags = append(tags, tag)
			}
		} else {
			break
		}
	}
	return tags
}

// skipContainer consumes bytes until the matching 0x08 end marker.
func skipContainer(r *vdfReader) {
	depth := 1
	for depth > 0 {
		b, ok := r.peekByte()
		if !ok {
			return
		}
		r.pos++
		if b == 0x00 {
			depth++
		} else if b == 0x08 {
			depth--
		}
	}
}

// extractFlatpakID extracts a Flatpak application ID from a shortcut exe string.
// Steam shortcuts store the exe in various formats:
//   "/usr/bin/flatpak run com.github.iwalton3.jellyfin-media-player"
//   "run" "--branch=stable" "--arch=x86_64" "--command=..." "org.jellyfin.JellyfinDesktop"
//   "/home/deck/game.sh" → "" (not a Flatpak)
//
// Strategy: find any token that looks like a reverse-DNS Flatpak ID (2+ dots).
func extractFlatpakID(exe string) string {
	// Strip outer quotes and whitespace
	exe = strings.Trim(exe, "\"' ")

	// Split on whitespace and quotes
	parts := strings.FieldsFunc(exe, func(r rune) bool {
		return r == ' ' || r == '"' || r == '\''
	})

	for _, part := range parts {
		part = strings.Trim(part, "\"' ")
		if part == "" {
			continue
		}
		// Skip flags
		if strings.HasPrefix(part, "-") {
			continue
		}
		// Skip common non-ID tokens
		if part == "run" || part == "flatpak" || part == "/usr/bin/flatpak" {
			continue
		}
		// Flatpak IDs are reverse-DNS: org.app.Name, com.github.user.app, etc.
		if strings.Count(part, ".") >= 2 {
			return part
		}
	}
	return ""
}

// sanitizeForID creates a safe ID from a name.
func sanitizeForID(name string) string {
	name = strings.ToLower(name)
	name = strings.ReplaceAll(name, " ", "_")
	name = strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '_' {
			return r
		}
		return -1
	}, name)
	if len(name) > 32 {
		name = name[:32]
	}
	return name
}

// vdfReader provides low-level binary VDF reading.
type vdfReader struct {
	data []byte
	pos  int
}

func (r *vdfReader) peekByte() (byte, bool) {
	if r.pos >= len(r.data) {
		return 0, false
	}
	return r.data[r.pos], true
}

func (r *vdfReader) skipByte(expected byte) bool {
	b, ok := r.peekByte()
	if !ok || b != expected {
		return false
	}
	r.pos++
	return true
}

// readString reads a null-terminated string.
func (r *vdfReader) readString() string {
	start := r.pos
	for r.pos < len(r.data) {
		if r.data[r.pos] == 0x00 {
			s := string(r.data[start:r.pos])
			r.pos++ // skip null terminator
			return s
		}
		r.pos++
	}
	return string(r.data[start:])
}

// readInt32 reads a little-endian int32.
func (r *vdfReader) readInt32() int32 {
	if r.pos+4 > len(r.data) {
		return 0
	}
	val := int32(binary.LittleEndian.Uint32(r.data[r.pos : r.pos+4]))
	r.pos += 4
	return val
}

