package jellyfin

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Plugin implements the Boiler Room plugin interface for Jellyfin.
// It communicates with a Jellyfin server to search media and control playback
// on the local device's active session.
type Plugin struct {
	serverURL string
	apiKey    string
	client    *http.Client
}

// NewPlugin creates a new Jellyfin plugin.
// serverURL: the base URL of the Jellyfin server (e.g., "http://<jellyfin-ip>:8096")
// apiKey: a Jellyfin API key for authentication
func NewPlugin(serverURL, apiKey string) *Plugin {
	return &Plugin{
		serverURL: strings.TrimRight(serverURL, "/"),
		apiKey:    apiKey,
		client: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

func (p *Plugin) Name() string    { return "jellyfin" }
func (p *Plugin) Version() string { return "0.1.0" }

func (p *Plugin) Capabilities() []string {
	return []string{"search", "play", "browse", "status"}
}

func (p *Plugin) GetState() map[string]interface{} {
	state := map[string]interface{}{
		"connected":  p.serverURL != "",
		"server_url": p.serverURL,
	}

	// Try to get current playback status
	sessions, err := p.getSessions()
	if err == nil && len(sessions) > 0 {
		for _, s := range sessions {
			if np, ok := s["NowPlayingItem"]; ok && np != nil {
				npMap, _ := np.(map[string]interface{})
				state["now_playing"] = npMap["Name"]
				state["media_type"] = npMap["Type"]
				break
			}
		}
	}

	return state
}

func (p *Plugin) HandleAction(action string, params map[string]interface{}) (interface{}, error) {
	switch action {
	case "search":
		query, _ := params["query"].(string)
		if query == "" {
			return nil, fmt.Errorf("search requires a 'query' parameter")
		}
		limit := 10
		if l, ok := params["limit"].(float64); ok {
			limit = int(l)
		}
		return p.search(query, limit)

	case "play":
		itemID, _ := params["item_id"].(string)
		if itemID == "" {
			// If no item_id, try search-and-play
			query, _ := params["query"].(string)
			if query == "" {
				return nil, fmt.Errorf("play requires 'item_id' or 'query'")
			}
			results, err := p.search(query, 1)
			if err != nil {
				return nil, err
			}
			if len(results) == 0 {
				return nil, fmt.Errorf("no results found for '%s'", query)
			}
			itemID, _ = results[0]["Id"].(string)
			if itemID == "" {
				return nil, fmt.Errorf("could not extract item ID from search result")
			}
		}
		return p.playItem(itemID)

	case "browse":
		parentID, _ := params["parent_id"].(string)
		return p.browse(parentID)

	case "status":
		return p.getPlaybackStatus()

	default:
		return nil, fmt.Errorf("unknown action: %s", action)
	}
}

// search queries the Jellyfin library.
func (p *Plugin) search(query string, limit int) ([]map[string]interface{}, error) {
	endpoint := fmt.Sprintf("%s/Items?searchTerm=%s&Limit=%d&Recursive=true&IncludeItemTypes=Movie,Series,Audio,MusicAlbum,Episode&api_key=%s",
		p.serverURL, url.QueryEscape(query), limit, p.apiKey)

	resp, err := p.client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("jellyfin search failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var result struct {
		Items []map[string]interface{} `json:"Items"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("failed to parse search results: %w", err)
	}

	// Simplify the response
	var items []map[string]interface{}
	for _, item := range result.Items {
		items = append(items, map[string]interface{}{
			"Id":   item["Id"],
			"Name": item["Name"],
			"Type": item["Type"],
			"Year": item["ProductionYear"],
		})
	}

	return items, nil
}

// playItem sends a play command to the local Jellyfin session.
func (p *Plugin) playItem(itemID string) (map[string]interface{}, error) {
	// Find the local session
	sessions, err := p.getSessions()
	if err != nil {
		return nil, fmt.Errorf("failed to get sessions: %w", err)
	}

	var sessionID string
	for _, s := range sessions {
		// Look for the local device session
		if client, ok := s["Client"].(string); ok {
			if strings.Contains(strings.ToLower(client), "jellyfin media player") ||
				strings.Contains(strings.ToLower(client), "jellyfin-mpv") {
				sessionID, _ = s["Id"].(string)
				break
			}
		}
	}

	if sessionID == "" {
		// Fall back to first session with a play queue capability
		for _, s := range sessions {
			if caps, ok := s["Capabilities"].(map[string]interface{}); ok {
				if playable, _ := caps["SupportsMediaControl"].(bool); playable {
					sessionID, _ = s["Id"].(string)
					break
				}
			}
		}
	}

	if sessionID == "" {
		return nil, fmt.Errorf("no active Jellyfin session found on this device — is Jellyfin Media Player running?")
	}

	// Send play command
	endpoint := fmt.Sprintf("%s/Sessions/%s/Playing?ItemIds=%s&PlayCommand=PlayNow&api_key=%s",
		p.serverURL, sessionID, itemID, p.apiKey)

	req, _ := http.NewRequest("POST", endpoint, nil)
	resp, err := p.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("play command failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("play command returned %d: %s", resp.StatusCode, string(body))
	}

	return map[string]interface{}{
		"status":     "playing",
		"item_id":    itemID,
		"session_id": sessionID,
	}, nil
}

// browse lists items in a Jellyfin library folder.
func (p *Plugin) browse(parentID string) ([]map[string]interface{}, error) {
	endpoint := p.serverURL + "/Items?"
	if parentID != "" {
		endpoint += "ParentId=" + parentID + "&"
	}
	endpoint += fmt.Sprintf("Recursive=false&SortBy=SortName&SortOrder=Ascending&api_key=%s", p.apiKey)

	resp, err := p.client.Get(endpoint)
	if err != nil {
		return nil, fmt.Errorf("browse failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var result struct {
		Items []map[string]interface{} `json:"Items"`
	}
	json.Unmarshal(body, &result)

	var items []map[string]interface{}
	for _, item := range result.Items {
		items = append(items, map[string]interface{}{
			"Id":       item["Id"],
			"Name":     item["Name"],
			"Type":     item["Type"],
			"IsFolder": item["IsFolder"],
		})
	}

	return items, nil
}

// getPlaybackStatus returns current playback info.
func (p *Plugin) getPlaybackStatus() (map[string]interface{}, error) {
	sessions, err := p.getSessions()
	if err != nil {
		return nil, err
	}

	for _, s := range sessions {
		if np, ok := s["NowPlayingItem"]; ok && np != nil {
			npMap, _ := np.(map[string]interface{})
			return map[string]interface{}{
				"status":     "playing",
				"item":       npMap["Name"],
				"type":       npMap["Type"],
				"session_id": s["Id"],
			}, nil
		}
	}

	return map[string]interface{}{
		"status": "idle",
	}, nil
}

// getSessions fetches active Jellyfin sessions.
func (p *Plugin) getSessions() ([]map[string]interface{}, error) {
	endpoint := fmt.Sprintf("%s/Sessions?api_key=%s", p.serverURL, p.apiKey)
	resp, err := p.client.Get(endpoint)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	var sessions []map[string]interface{}
	if err := json.Unmarshal(body, &sessions); err != nil {
		return nil, err
	}
	return sessions, nil
}
