package youtube

import (
	"fmt"
	"net/url"
	"os/exec"
	"strings"
)

// Plugin implements the Boiler Room plugin interface for YouTube.
// Since YouTube doesn't have a local API, this plugin opens the browser
// with search results or specific video URLs.
type Plugin struct {
	preferredBrowser string // Flatpak ID of preferred browser, or empty for system default
}

// NewPlugin creates a new YouTube plugin.
// browser can be:
//   - "" (empty) → use xdg-open (system default)
//   - "firefox" → shorthand for org.mozilla.firefox
//   - "chrome" → shorthand for com.google.Chrome
//   - "org.mozilla.firefox" → explicit Flatpak ID
func NewPlugin(browser string) *Plugin {
	// Resolve shorthands
	switch strings.ToLower(browser) {
	case "firefox":
		browser = "org.mozilla.firefox"
	case "chrome", "chromium":
		browser = "com.google.Chrome"
	}
	return &Plugin{preferredBrowser: browser}
}

func (p *Plugin) Name() string    { return "youtube" }
func (p *Plugin) Version() string { return "0.1.0" }

func (p *Plugin) Capabilities() []string {
	return []string{"search", "open"}
}

func (p *Plugin) GetState() map[string]interface{} {
	return map[string]interface{}{
		"preferred_browser": p.preferredBrowser,
	}
}

func (p *Plugin) HandleAction(action string, params map[string]interface{}) (interface{}, error) {
	switch action {
	case "search":
		query, _ := params["query"].(string)
		if query == "" {
			return nil, fmt.Errorf("search requires a 'query' parameter")
		}
		return p.openSearch(query)

	case "open":
		rawURL, _ := params["url"].(string)
		if rawURL == "" {
			return nil, fmt.Errorf("open requires a 'url' parameter")
		}
		return p.openURL(rawURL)

	default:
		return nil, fmt.Errorf("unknown action: %s", action)
	}
}

// openSearch opens YouTube search results for the given query.
func (p *Plugin) openSearch(query string) (map[string]interface{}, error) {
	searchURL := fmt.Sprintf("https://www.youtube.com/results?search_query=%s", url.QueryEscape(query))
	if err := p.launch(searchURL); err != nil {
		return nil, fmt.Errorf("failed to open YouTube search: %w", err)
	}
	return map[string]interface{}{
		"status": "opened",
		"url":    searchURL,
		"query":  query,
	}, nil
}

// openURL opens a specific YouTube URL.
func (p *Plugin) openURL(rawURL string) (map[string]interface{}, error) {
	if err := p.launch(rawURL); err != nil {
		return nil, fmt.Errorf("failed to open URL: %w", err)
	}
	return map[string]interface{}{
		"status": "opened",
		"url":    rawURL,
	}, nil
}

// launch opens a URL in the browser.
func (p *Plugin) launch(targetURL string) error {
	var cmd *exec.Cmd
	if p.preferredBrowser != "" {
		cmd = exec.Command("flatpak", "run", p.preferredBrowser, targetURL)
	} else {
		cmd = exec.Command("xdg-open", targetURL)
	}

	if err := cmd.Start(); err != nil {
		return err
	}
	go func() { _ = cmd.Wait() }()
	return nil
}
