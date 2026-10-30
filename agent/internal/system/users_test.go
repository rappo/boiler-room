package system

import "testing"

const sampleLoginUsers = `"users"
{
	"76561198000000001"
	{
		"AccountName"		"alpha"
		"PersonaName"		"Alpha Persona"
		"RememberPassword"		"1"
		"MostRecent"		"0"
		"Timestamp"		"1700000000"
	}
	"76561198000000002"
	{
		"AccountName"		"beta"
		"PersonaName"		"Beta \"quoted\""
		"MostRecent"		"1"
	}
}
`

func TestParseLoginUsers(t *testing.T) {
	users := parseLoginUsers(sampleLoginUsers)
	if len(users) != 2 {
		t.Fatalf("got %d users, want 2: %+v", len(users), users)
	}
	if users[0].SteamID != "76561198000000001" || users[0].AccountName != "alpha" || users[0].PersonaName != "Alpha Persona" || users[0].MostRecent {
		t.Errorf("user 0 parsed wrong: %+v", users[0])
	}
	if users[1].AccountName != "beta" || !users[1].MostRecent {
		t.Errorf("user 1 parsed wrong: %+v", users[1])
	}
}

func TestParseLoginUsersEmpty(t *testing.T) {
	if got := parseLoginUsers(`"users"
{
}
`); len(got) != 0 {
		t.Fatalf("expected no users, got %+v", got)
	}
}
