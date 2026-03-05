import json
import os
import sys
import uuid

def _project_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # foxmidi/config.py → go up one level to project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_FILE = os.path.join(_project_root(), "config.json")

# Per-mapping "settings" defaults — keyed by internal type name
MAPPING_SETTING_DEFAULTS = {
    "pad": {
        # timing flags live on each step ("fire") and each hold ("immediate")
    },
    "continuous": {
        # Shared by knob/fader AND slider/trackpad
        "sensitivity": 8,       # ticks-per-unit for zoom
        "smoothing":   0.3,     # for volume action
        "debounce_ms": 0,       # rate-limit in ms (raise for trackpad/slider)
        "invert":      False,   # flip 0↔127 (volume/zoom; mouse_move uses per-action axis/invert)
    },
}

DEFAULT_CONFIG = {
    "devices":  [],
    "mappings": [],
}

# ── Mapping schema ────────────────────────────────────────────────
# {
#   "id":         "<uuid8>",
#   "name":       "My Mapping",
#   "cc":         1,            # CC or note number
#   "msg_type":   "cc",         # "cc" | "note_on" | "note_off"
#   "input_type": "pad/button", # "pad/button" | "continuous"
#   "condition":  { "type": "any value", ... },
#   "actions":    [ { "action": {...}, "delay_ms": 0, "condition": {...} }, ... ],
#   "hold_actions": [           # pad/button only
#       { "threshold_ms": 300, "action": {...}, "condition": {...} }, ...
#   ],
#   "settings":   { ... }       # see MAPPING_SETTING_DEFAULTS["continuous"]
# }

def new_mapping_id():
    return str(uuid.uuid4())[:8]

def default_settings_for(input_type):
    key = {
        "pad/button": "pad",
        "continuous":  "continuous",
        # legacy labels still handled
        "knob/fader":      "continuous",
        "slider/trackpad": "continuous",
        "knob":   "continuous",
        "slider": "continuous",
    }.get(input_type, input_type)
    return dict(MAPPING_SETTING_DEFAULTS.get(key, {}))

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_FILE, "r") as f:
        data = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        if k not in data:
            data[k] = v
    return data

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)