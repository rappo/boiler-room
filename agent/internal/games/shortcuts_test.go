package games

import "testing"

func TestExtractFlatpakID(t *testing.T) {
	cases := map[string]string{
		`"/usr/bin/flatpak" run com.github.iwalton3.jellyfin-media-player`:                  "com.github.iwalton3.jellyfin-media-player",
		`run --branch=stable --arch=x86_64 --command=jellyfin org.jellyfin.JellyfinDesktop`: "org.jellyfin.JellyfinDesktop",
		`"/home/deck/game.sh"`: "",
		`"/usr/bin/flatpak" "run" "--file-forwarding" "tv.kodi.Kodi" "@@u" "%u" "@@"`: "tv.kodi.Kodi",
		``: "",
	}
	for in, want := range cases {
		if got := extractFlatpakID(in); got != want {
			t.Errorf("extractFlatpakID(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestSanitizeForID(t *testing.T) {
	if got := sanitizeForID("My Game: Deluxe Edition!"); got != "my_game_deluxe_edition" {
		t.Errorf("got %q", got)
	}
	long := sanitizeForID("aaaaaaaaaabbbbbbbbbbccccccccccddddddddddeeeeeeeeee")
	if len(long) != 32 {
		t.Errorf("expected 32-char cap, got %d", len(long))
	}
}
