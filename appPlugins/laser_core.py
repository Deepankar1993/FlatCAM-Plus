# Qt-free core logic for the Laser plugin. Importable in a headless context.
import json
import logging
import re
from copy import deepcopy

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


# a tiny non-zero marker diameter; laser uses zero offset so the value only labels the tool
LASER_MARKER_DIA = 0.1


def build_laser_tools_dict(geo_options, params, solid_geometry):
    """Build the single-tool dict that GeometryObject.mtool_gen_cncjob expects.

    geo_options: the source geometry's options dict (provides valid tools_mill_* defaults).
    params: dict with keys power_in_app(bool), power_pct, power_max, speed,
            air_assist(bool), laser_mode('M3'|'M4').
    solid_geometry: the geometry to trace.
    """
    data = {k: v for k, v in geo_options.items() if str(k).startswith('tools_mill_')}

    data['tools_mill_ppname_g'] = 'GRBL_laser_air_assist' if params['air_assist'] else 'GRBL_laser'
    data['tools_mill_feedrate'] = params['speed']
    data['tools_mill_laser_on'] = params['laser_mode']
    data['tools_mill_min_power'] = 0
    data['tools_mill_multidepth'] = False
    data['tools_mill_extracut'] = False
    data['tools_mill_offset_type'] = 0  # Path -> zero offset, no UI dependency

    if params['power_in_app']:
        s_val = int(round(float(params['power_pct']) / 100.0 * float(params['power_max'])))
        data['tools_mill_spindlespeed'] = s_val
    else:
        # empty -> preprocessor emits a bare M3/M4 so LaserGRBL controls power
        data['tools_mill_spindlespeed'] = ''

    return {
        1: {
            'tooldia': LASER_MARKER_DIA,
            'data': deepcopy(data),
            'solid_geometry': solid_geometry,
        }
    }


_LASER_ON_RE = re.compile(r'^\s*M0?[34]\b', re.IGNORECASE)
_LASER_OFF_RE = re.compile(r'^\s*M0?5\b', re.IGNORECASE)


def repeat_cut_passes(gcode, n_passes):
    """Repeat the cut body of a laser tool's G-code n_passes times.

    The body spans from the first laser-on line (M3/M4) through the last laser-off
    line (M5). Returns (new_gcode, ok); ok is False (gcode returned unchanged) when
    the seam markers cannot be located, so the caller can honestly fall back to a
    single pass.
    """
    if not n_passes or int(n_passes) <= 1:
        return gcode, True

    lines = gcode.splitlines()
    first_on = next((i for i, ln in enumerate(lines) if _LASER_ON_RE.match(ln)), None)
    last_off = next((i for i in range(len(lines) - 1, -1, -1) if _LASER_OFF_RE.match(lines[i])), None)
    if first_on is None or last_off is None or last_off <= first_on:
        return gcode, False

    header = lines[:first_on]
    body = lines[first_on:last_off + 1]   # inclusive of laser-on .. laser-off
    footer = lines[last_off + 1:]

    new_lines = header + body * int(n_passes) + footer
    return "\n".join(new_lines) + ("\n" if gcode.endswith("\n") else ""), True
