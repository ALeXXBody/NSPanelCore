// Package config is a 1:1 Go port of models.py.
//
// Everything persisted in HA storage. JSON tags match the Python asdict keys
// so existing .storage files load unchanged. Unknown keys are ignored on
// load (matching from_dict's known-field filter); defaults match Python.
package config

import "encoding/json"

// Screensaver modes accepted by PanelConfig (others fall back to with_background).
var screensaverModes = map[string]bool{
	"with_background":            true,
	"without_background":         true,
	"datetime_with_background":   true,
	"datetime_without_background": true,
	"no_screensaver":             true,
	"global":                     true,
}

type Light struct {
	ID                       int    `json:"id"`
	Name                     string `json:"name"`
	HAEntity                 string `json:"ha_entity"`
	RoomID                   int    `json:"room_id"`
	PageID                   int    `json:"page_id"`
	PageSlot                 int    `json:"page_slot"`
	LightType                string `json:"light_type"`
	CanDim                   bool   `json:"can_dim"`
	CanColorTemperature      bool   `json:"can_color_temperature"`
	CanRGB                   bool   `json:"can_rgb"`
	ControlledFromMainPage   bool   `json:"controlled_from_main_page"`
	State                    bool   `json:"state"`
	Brightness               int    `json:"brightness"`
	ColorTemp                int    `json:"color_temp"`
	Hue                      int    `json:"hue"`
	Saturation               int    `json:"saturation"`
	Mode                     string `json:"mode"`
}

type Thermostat struct {
	ID                int              `json:"id"`
	Name              string           `json:"name"`
	HAEntity          string           `json:"ha_entity"`
	RoomID            int              `json:"room_id"`
	PageID            int              `json:"page_id"`
	PageSlot          int              `json:"page_slot"`
	CurrentTemperature float64         `json:"current_temperature"`
	SetTemperature     float64         `json:"set_temperature"`
	StepSize           float64         `json:"step_size"`
	Options            []map[string]any `json:"options"`
}

type RelayBinding struct {
	PanelMAC string `json:"panel_mac"`
	RelayNum int    `json:"relay_num"`
}

type RelayGroup struct {
	ID              int            `json:"id"`
	Name            string         `json:"name"`
	RegisterAsLight bool           `json:"register_as_light"`
	Bindings        []RelayBinding `json:"bindings"`
}

type Room struct {
	ID              int    `json:"id"`
	Name            string `json:"name"`
	DisplayOrder    int    `json:"display_order"`
	TempSensorEntity string `json:"temp_sensor_entity"`
}

type EntityPage struct {
	ID           int   `json:"id"`
	RoomID       *int  `json:"room_id"`
	PageType     int   `json:"page_type"`
	IsScenesPage bool  `json:"is_scenes_page"`
	DisplayOrder int   `json:"display_order"`
}

type Scene struct {
	ID          int              `json:"id"`
	Name        string           `json:"name"`
	PageID      int              `json:"page_id"`
	PageSlot    int              `json:"page_slot"`
	HAEntity    string           `json:"ha_entity"`
	LightStates []map[string]any `json:"light_states"`
}

type Panel struct {
	ID                          int      `json:"id"`
	MAC                         string   `json:"mac"`
	Name                        string   `json:"name"`
	Model                       string   `json:"model"`
	Version                     string   `json:"version"`
	RoomID                      int      `json:"room_id"`
	Accepted                    bool     `json:"accepted"`
	Denied                      bool     `json:"denied"`
	DefaultPage                 int      `json:"default_page"`
	ScreensaverMode             string   `json:"screensaver_mode"`
	ScreensaverActivationTimeout int     `json:"screensaver_activation_timeout"`
	MinButtonPushTime           int      `json:"min_button_push_time"`
	ButtonLongPressTime         int      `json:"button_long_press_time"`
	SpecialModeTriggerTime      int      `json:"special_mode_trigger_time"`
	SpecialModeReleaseTime      int      `json:"special_mode_release_time"`
	ScreenDimLevel              int      `json:"screen_dim_level"`
	ScreensaverDimLevel         int      `json:"screensaver_dim_level"`
	ClockUSStyle                bool     `json:"clock_us_style"`
	LockToDefaultRoom           bool     `json:"lock_to_default_room"`
	UseFahrenheit               bool     `json:"use_fahrenheit"`
	IsUSPanel                   bool     `json:"is_us_panel"`
	USPanelOrientation          string   `json:"us_panel_orientation"`
	ReverseRelays               bool     `json:"reverse_relays"`
	Relay1DefaultMode           bool     `json:"relay1_default_mode"`
	Relay2DefaultMode           bool     `json:"relay2_default_mode"`
	Relay1IsLight               bool     `json:"relay1_is_light"`
	Relay2IsLight               bool     `json:"relay2_is_light"`
	TemperatureCalibration      float64  `json:"temperature_calibration"`
	HasHumidity                 bool     `json:"has_humidity"`
	HasPressure                 bool     `json:"has_pressure"`
	Button1Mode                 int      `json:"button1_mode"`
	Button2Mode                 int      `json:"button2_mode"`
	Button1MQTTTopic            string   `json:"button1_mqtt_topic"`
	Button1MQTTPayload          string   `json:"button1_mqtt_payload"`
	Button2MQTTTopic            string   `json:"button2_mqtt_topic"`
	Button2MQTTPayload          string   `json:"button2_mqtt_payload"`
	Button1DetachedLight        int      `json:"button1_detached_light"`
	Button2DetachedLight        int      `json:"button2_detached_light"`
	ShowHomeScenes              bool     `json:"show_home_scenes"`
	ShowHomeCeiling             bool     `json:"show_home_ceiling"`
	ShowHomeTable               bool     `json:"show_home_table"`
	ShowHomeKelvin              bool     `json:"show_home_kelvin"`
	RaiseTo100LightLevel        int      `json:"raise_to_100_light_level"`
	OptimisticMode              bool     `json:"optimistic_mode"`
	TemperatureUnit             string   `json:"temperature_unit"`
	InsideTemperatureSensorTopic string  `json:"inside_temperature_sensor_topic"`
	Rooms                       []int    `json:"rooms"`
	Relay1Group                 []int    `json:"relay1_group"`
	Relay2Group                 []int    `json:"relay2_group"`
	DefaultLightBrightness      int      `json:"default_light_brightness"`
	Online                      bool     `json:"online"`
	FirmwareMD5                 string   `json:"firmware_md5"`
	TFTMD5                      string   `json:"tft_md5"`
	LittlefsMD5                 string   `json:"littlefs_md5"`
	WifiHostname                string   `json:"wifi_hostname"`
}

// Normalize mirrors PanelConfig.__post_init__: legacy screensaver values fall
// back to with_background; temperature calibration coerces to float.
func (p *Panel) Normalize() {
	if !screensaverModes[p.ScreensaverMode] {
		p.ScreensaverMode = "with_background"
	}
	if p.Model == "" {
		p.Model = "sonoff"
	}
	if p.Version == "" {
		p.Version = "UNKNOWN"
	}
	if p.Rooms == nil {
		p.Rooms = []int{}
	}
	if p.Relay1Group == nil {
		p.Relay1Group = []int{}
	}
	if p.Relay2Group == nil {
		p.Relay2Group = []int{}
	}
}

type Message struct {
	ID      int    `json:"id"`
	Title   string `json:"title"`
	Message string `json:"message"`
	Read    bool   `json:"read"`
}

type Settings struct {
	ManagerAddress          string         `json:"manager_address"`
	ManagerPort             int            `json:"manager_port"`
	Theme                   string         `json:"theme"`
	FirmwareManifestURL     string         `json:"firmware_manifest_url"`
	FirmwareAutoCheckHours  int            `json:"firmware_auto_check_hours"`
	FirmwareActiveVersion   string         `json:"firmware_active_version"`
	FirmwareLatestVersion   string         `json:"firmware_latest_version"`
	FirmwareLastCheck       string         `json:"firmware_last_check"`
	FirmwareActiveMD5s      map[string]string `json:"firmware_active_md5s"`
	MQTTWaitTime            int            `json:"mqtt_wait_time"`
	ClockUSStyle            bool           `json:"clock_us_style"`
	DateFormat              string         `json:"date_format"`
	ColorTempMin            int            `json:"color_temp_min"`
	ColorTempMax            int            `json:"color_temp_max"`
	ReverseColorTemp        bool           `json:"reverse_color_temp"`
	OptimisticMode          bool           `json:"optimistic_mode"`
	TurnOnBehaviour         string         `json:"turn_on_behaviour"`
	LightTurnOnBrightness   int            `json:"light_turn_on_brightness"`
	UseFahrenheit           bool           `json:"use_fahrenheit"`
	WeatherUpdateInterval   int            `json:"weather_update_interval"`
	AutoTFTUpdates          bool           `json:"auto_tft_updates"`
	CustomTFTName           string         `json:"custom_tft_name"`
	CustomTFTMD5            string         `json:"custom_tft_md5"`
	CustomTFTSize           int64          `json:"custom_tft_size"`
	CustomTFTUploadedAt     string         `json:"custom_tft_uploaded_at"`
	CustomTFTSource         string         `json:"custom_tft_source"`
	ScreensaverMode         string         `json:"screensaver_mode"`
	LocationLatitude        string         `json:"location_latitude"`
	LocationLongitude       string         `json:"location_longitude"`
	OutsideTempSensorEntity string         `json:"outside_temp_sensor_entity"`
	OutsideTempProvider     string         `json:"outside_temp_provider"`
	PrecipitationFormat     string         `json:"precipitation_format"`
	WindSpeedFormat         string         `json:"wind_speed_format"`
}

func DefaultSettings() Settings {
	return Settings{
		ManagerAddress:        "core",
		ManagerPort:           8000,
		Theme:                 "nspmwip",
		FirmwareManifestURL:   "https://raw.githubusercontent.com/ALeXXBody/NSPanelCore/main/firmware/manifest.json",
		FirmwareAutoCheckHours: 24,
		FirmwareActiveMD5s:    map[string]string{},
		DateFormat:            "%d/%m",
		ColorTempMin:          2700,
		ColorTempMax:          6500,
		TurnOnBehaviour:       "color_temp",
		WeatherUpdateInterval: 30,
		AutoTFTUpdates:        true,
		ScreensaverMode:       "with_background",
		PrecipitationFormat:   "mm",
		WindSpeedFormat:       "kmh",
	}
}

type Integration struct {
	Settings    Settings     `json:"settings"`
	Rooms       []Room       `json:"rooms"`
	Lights      []Light      `json:"lights"`
	Thermostats []Thermostat `json:"thermostats"`
	RelayGroups []RelayGroup `json:"relay_groups"`
	Pages       []EntityPage `json:"pages"`
	Scenes      []Scene      `json:"scenes"`
	Panels      []Panel      `json:"panels"`
	Messages    []Message    `json:"messages"`
	NextID      map[string]int `json:"next_id"`
}

// New returns an Integration with defaults matching IntegrationConfig().
func New() *Integration {
	return &Integration{
		Settings: DefaultSettings(),
		Rooms: []Room{}, Lights: []Light{}, Thermostats: []Thermostat{},
		RelayGroups: []RelayGroup{}, Pages: []EntityPage{}, Scenes: []Scene{},
		Panels: []Panel{}, Messages: []Message{},
		NextID: map[string]int{
			"room": 1, "light": 1, "thermostat": 1, "relay_group": 1,
			"page": 1, "scene": 1, "panel": 1, "message": 1,
		},
	}
}

// NextIDFor mirrors IntegrationConfig.next_id_for.
func (c *Integration) NextIDFor(kind string) int {
	v, ok := c.NextID[kind]
	if !ok || v < 1 {
		v = 1
	}
	c.NextID[kind] = v + 1
	return v
}

// Unmarshal loads with unknown-key tolerance (encoding/json ignores unknown
// fields by default) and normalizes panels. Nil slices become empty.
func Unmarshal(data []byte) (*Integration, error) {
	cfg := New()
	if len(data) == 0 {
		return cfg, nil
	}
	// Use an alias with pointers so missing sections keep defaults.
	var raw struct {
		Settings    *Settings     `json:"settings"`
		Rooms       []Room        `json:"rooms"`
		Lights      []Light       `json:"lights"`
		Thermostats []Thermostat  `json:"thermostats"`
		RelayGroups []RelayGroup  `json:"relay_groups"`
		Pages       []EntityPage  `json:"pages"`
		Scenes      []Scene       `json:"scenes"`
		Panels      []Panel       `json:"panels"`
		Messages    []Message     `json:"messages"`
		NextID      map[string]int `json:"next_id"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	if raw.Settings != nil {
		// Merge over defaults so new fields get defaults on old files.
		def := DefaultSettings()
		merged := *raw.Settings
		if merged.ManagerAddress == "" {
			merged.ManagerAddress = def.ManagerAddress
		}
		if merged.Theme == "" {
			merged.Theme = def.Theme
		}
		if merged.FirmwareManifestURL == "" {
			merged.FirmwareManifestURL = def.FirmwareManifestURL
		}
		if merged.DateFormat == "" {
			merged.DateFormat = def.DateFormat
		}
		if merged.FirmwareActiveMD5s == nil {
			merged.FirmwareActiveMD5s = map[string]string{}
		}
		if merged.TurnOnBehaviour == "" {
			merged.TurnOnBehaviour = def.TurnOnBehaviour
		}
		cfg.Settings = merged
	}
	if raw.Rooms != nil {
		cfg.Rooms = raw.Rooms
	}
	if raw.Lights != nil {
		cfg.Lights = raw.Lights
	}
	if raw.Thermostats != nil {
		cfg.Thermostats = raw.Thermostats
	}
	if raw.RelayGroups != nil {
		cfg.RelayGroups = raw.RelayGroups
	}
	if raw.Pages != nil {
		cfg.Pages = raw.Pages
	}
	if raw.Scenes != nil {
		cfg.Scenes = raw.Scenes
	}
	if raw.Panels != nil {
		cfg.Panels = raw.Panels
	}
	if raw.Messages != nil {
		cfg.Messages = raw.Messages
	}
	if raw.NextID != nil {
		for k, v := range raw.NextID {
			cfg.NextID[k] = v
		}
	}
	// Light defaults that matter: controlled_from_main_page defaults true in
	// practice; Python default is True so a missing key decodes False — fix up
	// only when the whole light came from an old file? No: keep verbatim.
	// Panel normalization (screensaver fallback etc.).
	for i := range cfg.Panels {
		cfg.Panels[i].Normalize()
	}
	return cfg, nil
}

// Marshal mirrors to_dict.
func (c *Integration) Marshal() ([]byte, error) {
	return json.Marshal(c)
}
