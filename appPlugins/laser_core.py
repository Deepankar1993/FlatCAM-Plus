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


def build_laser_tools_dict(geo_options, params, solid_geometry, beam_width=LASER_MARKER_DIA):
    """Build the single-tool dict that the milling engine expects.

    geo_options: the source geometry's options dict (provides valid tools_mill_* defaults).
    params: dict with keys power_in_app(bool), power_pct, power_max, speed,
            air_assist(bool), laser_mode('M3'|'M4').
    solid_geometry: the geometry to trace.
    beam_width: the laser spot diameter; used as the tool diameter (laser cuts with
                zero offset, so the value only labels the tool and sizes the plot).
    """
    data = {k: v for k, v in geo_options.items() if str(k).startswith('tools_mill_')}

    # Use the laser preprocessor chosen in the Laser tool; fall back to a sensible
    # GRBL laser default (air-assist variant when air assist is on) if none was passed.
    ppname = params.get('ppname')
    if not ppname:
        ppname = 'GRBL_laser_air_assist' if params['air_assist'] else 'GRBL_laser'
    data['tools_mill_ppname_g'] = ppname
    data['tools_mill_feedrate'] = params['speed']
    data['tools_mill_laser_on'] = params['laser_mode']
    data['tools_mill_min_power'] = 0
    data['tools_mill_multidepth'] = False
    data['tools_mill_extracut'] = False
    data['tools_mill_offset_type'] = 0  # Path -> zero offset, no UI dependency
    # the engine reads the tool diameter from the data dict
    data['tools_mill_tooldia'] = beam_width

    # An S (power) value MUST be written into the G-code: GRBL drives the laser by the
    # S word, and LaserGRBL streams the file verbatim - it does NOT inject power into
    # bare M3/M4 moves. A file with no S (or S0) runs the whole job at zero power.
    power_max = float(params['power_max'])
    if params['power_in_app']:
        # exact power baked from the chosen percentage
        s_val = int(round(float(params['power_pct']) / 100.0 * power_max))
    else:
        # "Set in LaserGRBL": export at full power so the file actually burns; the
        # operator scales it down live with GRBL's real-time power override slider.
        s_val = int(round(power_max))
    data['tools_mill_spindlespeed'] = s_val

    return {
        1: {
            'tooldia': beam_width,
            'data': deepcopy(data),
            'solid_geometry': solid_geometry,
        }
    }


def flatten_geometry(geometry):
    """Flatten an arbitrarily nested list of shapely geometries into a flat list."""
    if geometry is None:
        return []
    if isinstance(geometry, (list, tuple)):
        flat = []
        for geo in geometry:
            flat.extend(flatten_geometry(geo))
        return flat
    return [geometry]


def widen_passes(solid_geometry, beam_width, n_passes, overlap_pct):
    """Build the geometry for sideways-overlapping passes that widen the cut groove.

    Pass 1 traces the original geometry; every further pass k traces the boundary of
    the original buffered by k * step, where step = beam_width * (1 - overlap_pct/100).
    This is what makes the laser remove a band of material (e.g. widening a PCB
    isolation gap) instead of re-burning the same hairline.

    Returns (geometry_list, ok). ok is False (and the original geometry is returned)
    when the inputs cannot produce a widened path - the caller should fall back to
    plain repeated passes.
    """
    geoms = flatten_geometry(solid_geometry)
    n = int(n_passes) if n_passes else 1
    if n <= 1:
        return geoms, True
    if not geoms:
        return geoms, False

    step = float(beam_width) * (1.0 - float(overlap_pct) / 100.0)
    if step <= 0:
        return geoms, False

    try:
        from shapely.ops import unary_union
        merged = unary_union(geoms)
        out = list(geoms)
        for k in range(1, n):
            ring = merged.buffer(k * step).boundary
            if not ring.is_empty:
                out.append(ring)
        return out, True
    except Exception as e:
        log.warning("laser_core.widen_passes(): could not widen the geometry (%s)." % str(e))
        return geoms, False


_LASER_ON_RE = re.compile(r'^\s*M0?[34]\b', re.IGNORECASE)
_LASER_OFF_RE = re.compile(r'^\s*M0?5\b', re.IGNORECASE)
# Positioning lines the engine emits right before the first laser-on:
# - a rapid move ("G0 ..." / "G00 ...") to the cut start point
_PRE_CUT_RAPID_RE = re.compile(r'^\s*G0?0\b', re.IGNORECASE)
# - a feedrate-only line ("G1 F300.00" / "G01 F300.00"), no coordinates
_PRE_CUT_FEED_RE = re.compile(r'^\s*G0?1\s+F[\d.]+\s*$', re.IGNORECASE)


def repeat_cut_passes(gcode, n_passes):
    """Repeat the cut body of a laser tool's G-code n_passes times.

    The body spans from the first laser-on line (M3/M4) through the last laser-off
    line (M5), extended backwards to include the contiguous positioning rapid /
    feedrate-only lines that immediately precede the first laser-on. Including
    those lines makes every pass rapid back to the cut start with the laser off
    (the previous pass's body ends with M5), so open paths are re-traced from
    their true start instead of burning a stray segment from the previous pass's
    end point. Returns (new_gcode, ok); ok is False (gcode returned unchanged)
    when the seam markers cannot be located, so the caller can honestly fall
    back to a single pass.
    """
    if not n_passes or int(n_passes) <= 1:
        return gcode, True

    lines = gcode.splitlines()
    first_on = next((i for i, ln in enumerate(lines) if _LASER_ON_RE.match(ln)), None)
    last_off = next((i for i in range(len(lines) - 1, -1, -1) if _LASER_OFF_RE.match(lines[i])), None)
    if first_on is None or last_off is None or last_off <= first_on:
        return gcode, False

    # pull the contiguous pre-cut positioning/feedrate lines into the body
    body_start = first_on
    while body_start > 0 and (
            _PRE_CUT_RAPID_RE.match(lines[body_start - 1]) or
            _PRE_CUT_FEED_RE.match(lines[body_start - 1])):
        body_start -= 1

    header = lines[:body_start]
    body = lines[body_start:last_off + 1]   # pre-cut rapid .. laser-on .. laser-off
    footer = lines[last_off + 1:]

    new_lines = header + body * int(n_passes) + footer
    return "\n".join(new_lines) + ("\n" if gcode.endswith("\n") else ""), True
