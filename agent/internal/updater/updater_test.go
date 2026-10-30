package updater

import "testing"

func TestEnabledOnlyForReleaseBuilds(t *testing.T) {
	cases := []struct {
		repo, version string
		want          bool
	}{
		{"https://github.com/rappo/boiler-room", "0.5.3", true},
		{"https://github.com/rappo/boiler-room", "0.5.3-rc1", true},
		{"https://github.com/rappo/boiler-room", "dev", false},
		{"https://github.com/rappo/boiler-room", "dev-b650f28", false},
		{"https://github.com/rappo/boiler-room", "main", false},
		{"https://github.com/rappo/boiler-room", "v0.5.3", false},
		{"", "0.5.3", false},
	}
	for _, c := range cases {
		if got := NewUpdater(c.repo, c.version).Enabled(); got != c.want {
			t.Errorf("Enabled(repo=%q, version=%q) = %v, want %v", c.repo, c.version, got, c.want)
		}
	}
}
