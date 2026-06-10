# Qt-free core logic for the Laser plugin. Importable in a headless context.
import json
import logging

log = logging.getLogger('base')

# Built-in fallback, kept in sync with assets/resources/laser_presets.json
BUILTIN_PRESETS = [
    {"name": "PCB — surface mark", "power_pct": 35, "speed": 600, "passes": 1, "air_assist": True, "laser_mode": "M4"},
    {"name": "Plywood 3 mm — cut", "power_pct": 100, "speed": 180, "passes": 4, "air_assist": True, "laser_mode": "M3"},
    {"name": "Cardstock — cut", "power_pct": 60, "speed": 400, "passes": 1, "air_assist": True, "laser_mode": "M3"},
    {"name": "Vinyl — cut", "power_pct": 45, "speed": 350, "passes": 1, "air_assist": True, "laser_mode": "M3"},
    {"name": "Wood — engrave", "power_pct": 50, "speed": 800, "passes": 1, "air_assist": True, "laser_mode": "M4"},
    {"name": "Acrylic — engrave", "power_pct": 40, "speed": 500, "passes": 1, "air_assist": True, "laser_mode": "M4"},
    {"name": "Custom", "power_pct": 100, "speed": 300, "passes": 1, "air_assist": True, "laser_mode": "M4"},
]

REQUIRED_KEYS = {"name", "power_pct", "speed", "passes", "air_assist", "laser_mode"}


def load_laser_presets(path):
    """Load laser material presets from a JSON file, falling back to BUILTIN_PRESETS
    if the file is missing, unreadable, malformed, or has no valid entries."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        valid = [p for p in data if isinstance(p, dict) and REQUIRED_KEYS <= set(p)]
        if valid:
            return valid
        log.warning("laser_core.load_laser_presets(): no valid presets in %s, using built-in." % path)
    except Exception as e:
        log.warning("laser_core.load_laser_presets(): could not load %s (%s), using built-in." % (path, e))
    return list(BUILTIN_PRESETS)
