package main

import "testing"

func TestVersionLabel(t *testing.T) {
	defer func(v string) { version = v }(version)
	for in, want := range map[string]string{
		"0.5.3":       "v0.5.3",
		"dev":         "dev",
		"dev-b650f28": "dev-b650f28",
	} {
		version = in
		if got := versionLabel(); got != want {
			t.Errorf("versionLabel() with version=%q = %q, want %q", in, got, want)
		}
	}
}
