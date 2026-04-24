package plugins

import (
	"fmt"
	"log"
	"sync"
)

// Plugin defines the interface that all Boiler Room plugins must implement.
type Plugin interface {
	// Name returns the plugin's unique identifier (e.g., "jellyfin", "youtube").
	Name() string

	// Version returns the plugin version string.
	Version() string

	// Capabilities returns a list of supported actions (e.g., ["search", "play", "browse"]).
	Capabilities() []string

	// HandleAction is called when a client sends a plugin action request.
	HandleAction(action string, params map[string]interface{}) (interface{}, error)

	// GetState returns the plugin's current state (for HA sensor sync).
	GetState() map[string]interface{}
}

// PluginInfo describes a registered plugin for API responses.
type PluginInfo struct {
	Name         string   `json:"name"`
	Version      string   `json:"version"`
	Status       string   `json:"status"` // "active", "inactive", "error"
	Capabilities []string `json:"capabilities"`
}

// Manager handles plugin registration and dispatch.
type Manager struct {
	mu      sync.RWMutex
	plugins map[string]Plugin
}

// NewManager creates a new plugin manager.
func NewManager() *Manager {
	return &Manager{
		plugins: make(map[string]Plugin),
	}
}

// Register adds a plugin to the manager.
func (m *Manager) Register(p Plugin) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	name := p.Name()
	if _, exists := m.plugins[name]; exists {
		return fmt.Errorf("plugin '%s' is already registered", name)
	}

	m.plugins[name] = p
	log.Printf("Plugin registered: %s v%s (capabilities: %v)", name, p.Version(), p.Capabilities())
	return nil
}

// Get returns a plugin by name.
func (m *Manager) Get(name string) (Plugin, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	p, ok := m.plugins[name]
	return p, ok
}

// List returns info about all registered plugins.
func (m *Manager) List() []PluginInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var list []PluginInfo
	for _, p := range m.plugins {
		list = append(list, PluginInfo{
			Name:         p.Name(),
			Version:      p.Version(),
			Status:       "active",
			Capabilities: p.Capabilities(),
		})
	}
	return list
}

// HandleAction dispatches an action to the named plugin.
func (m *Manager) HandleAction(pluginName, action string, params map[string]interface{}) (interface{}, error) {
	m.mu.RLock()
	p, ok := m.plugins[pluginName]
	m.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("plugin '%s' not found", pluginName)
	}

	// Validate the action is in capabilities
	caps := p.Capabilities()
	valid := false
	for _, cap := range caps {
		if cap == action {
			valid = true
			break
		}
	}
	if !valid {
		return nil, fmt.Errorf("plugin '%s' does not support action '%s' (capabilities: %v)", pluginName, action, caps)
	}

	return p.HandleAction(action, params)
}

// GetStates returns the current state of all plugins.
func (m *Manager) GetStates() map[string]map[string]interface{} {
	m.mu.RLock()
	defer m.mu.RUnlock()

	states := make(map[string]map[string]interface{})
	for name, p := range m.plugins {
		states[name] = p.GetState()
	}
	return states
}
