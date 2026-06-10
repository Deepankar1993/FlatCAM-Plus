# Laser Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a laser-first "Laser" plugin to FlatCAM that turns a Gerber or Geometry object into a LaserGRBL-ready G-code file using material presets and laser vocabulary, hiding all milling jargon.

**Architecture:** A Qt-free core module (`appPlugins/laser_core.py`) holds the pure logic — preset loading, laser tools-dict building, and multi-pass G-code repetition — so it is verifiable headless. A thin Qt plugin (`appPlugins/ToolLaser.py`, `class ToolLaser(AppTool)`) provides the panel and drives the existing generation engine (`GeometryObject.mtool_gen_cncjob`) and export path (`CNCJobObject.export_gcode`). Gerber sources are auto-traced to centerline geometry via `GerberObject.follow_geo`.

**Tech Stack:** Python 3.11, PyQt6, the existing FlatCAM plugin/AppTool framework, the `GRBL_laser_air_assist` / `GRBL_laser` preprocessors.

---

## Testing note

This repo has no unit-test framework. Tests in this plan are **standalone headless harness scripts** run with the build venv interpreter, following the proven pattern already used in this branch (the preprocessor `pp_check.py`). Each test script lives under `tests_laser/` (gitignored scratch dir) and is run with:

```
.venv-build\Scripts\python tests_laser\<name>.py
```

The core module is import-safe without Qt, so its tests need no GUI. The end-to-end test drives a scripted app run.

Add `tests_laser/` to `.gitignore` in Task 1 so scratch artifacts are never committed.

---

## File structure

- Create `appPlugins/laser_core.py` — Qt-free pure logic (presets, tools-dict, passes).
- Create `assets/resources/laser_presets.json` — shipped, user-editable preset list.
- Create `appPlugins/ToolLaser.py` — Qt plugin: panel + handlers.
- Modify `defaults.py` — add `tools_laser_*` factory defaults.
- Modify `appPlugins/__init__.py` — export `ToolLaser`.
- Modify `appMain.py` — instantiate and register the plugin.
- Modify `.gitignore` — ignore `tests_laser/`.
- Modify `CHANGELOG.md` — record the feature.

---

## Task 1: Factory defaults + gitignore

**Files:**
- Modify: `defaults.py` (the `tools_mill_*` block ends around line 481; add a new block after it)
- Modify: `.gitignore`

- [ ] **Step 1: Add laser defaults**

In `defaults.py`, immediately after the existing `"tools_mill_..."` entries (after line `"tools_mill_extracut": False,` and its siblings — locate the end of the mill block), add:

```python
        # ######################################################################
        # ################ Laser Plugin ########################################
        # ######################################################################
        "tools_laser_power_max": 1000,
        "tools_laser_power_pct": 100,
        "tools_laser_power_in_app": True,
        "tools_laser_speed": 300,
        "tools_laser_passes": 1,
        "tools_laser_air_assist": True,
        "tools_laser_mode": "M4",
        "tools_laser_preset": "PCB — surface mark",
        "tools_laser_last_export_folder": "",
```

- [ ] **Step 2: Ignore the scratch test dir**

In `.gitignore`, add a line:

```
tests_laser/
```

- [ ] **Step 3: Verify defaults import**

Run: `.venv-build\Scripts\python -c "import defaults; d=defaults.AppDefaults(); print(d['tools_laser_power_max'], d['tools_laser_mode'])"`
Expected: `1000 M4`

(If `AppDefaults()` needs args, instead run `python -c "import defaults; print('tools_laser_power_max' in defaults.AppDefaults.factory_defaults)"` expecting `True`.)

- [ ] **Step 4: Commit**

```
git add defaults.py .gitignore
git commit -m "Add tools_laser_* factory defaults"
```

---

## Task 2: Material presets file + loader

**Files:**
- Create: `assets/resources/laser_presets.json`
- Create: `appPlugins/laser_core.py`
- Test: `tests_laser/test_presets.py`

- [ ] **Step 1: Write the preset file**

Create `assets/resources/laser_presets.json`:

```json
[
  { "name": "PCB — surface mark", "power_pct": 35, "speed": 600, "passes": 1, "air_assist": true, "laser_mode": "M4" },
  { "name": "Plywood 3 mm — cut", "power_pct": 100, "speed": 180, "passes": 4, "air_assist": true, "laser_mode": "M3" },
  { "name": "Cardstock — cut", "power_pct": 60, "speed": 400, "passes": 1, "air_assist": true, "laser_mode": "M3" },
  { "name": "Vinyl — cut", "power_pct": 45, "speed": 350, "passes": 1, "air_assist": true, "laser_mode": "M3" },
  { "name": "Wood — engrave", "power_pct": 50, "speed": 800, "passes": 1, "air_assist": true, "laser_mode": "M4" },
  { "name": "Acrylic — engrave", "power_pct": 40, "speed": 500, "passes": 1, "air_assist": true, "laser_mode": "M4" },
  { "name": "Custom", "power_pct": 100, "speed": 300, "passes": 1, "air_assist": true, "laser_mode": "M4" }
]
```

- [ ] **Step 2: Write the failing test**

Create `tests_laser/test_presets.py`:

```python
import os, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from appPlugins import laser_core

# real file loads and contains the PCB preset first
presets = laser_core.load_laser_presets(os.path.join(ROOT, 'assets', 'resources', 'laser_presets.json'))
assert presets[0]['name'] == 'PCB — surface mark', presets[0]
assert any(p['name'] == 'Custom' for p in presets)
for p in presets:
    assert set(p) >= {'name', 'power_pct', 'speed', 'passes', 'air_assist', 'laser_mode'}, p

# missing file -> built-in fallback, no crash
fb = laser_core.load_laser_presets(os.path.join(tempfile.gettempdir(), 'nope_does_not_exist.json'))
assert any(x['name'] == 'Custom' for x in fb), fb

# corrupt file -> built-in fallback
bad = os.path.join(tempfile.gettempdir(), 'bad_presets.json')
open(bad, 'w').write('{ this is not json')
fb2 = laser_core.load_laser_presets(bad)
assert any(x['name'] == 'Custom' for x in fb2), fb2

print("test_presets OK")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv-build\Scripts\python tests_laser\test_presets.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'appPlugins.laser_core'`

- [ ] **Step 4: Write minimal implementation**

Create `appPlugins/laser_core.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv-build\Scripts\python tests_laser\test_presets.py`
Expected: `test_presets OK`

- [ ] **Step 6: Commit**

```
git add appPlugins/laser_core.py assets/resources/laser_presets.json
git commit -m "Add laser material presets file and loader"
```

---

## Task 3: Laser tools-dict builder

**Files:**
- Modify: `appPlugins/laser_core.py`
- Test: `tests_laser/test_tools_dict.py`

The milling engine (`GeometryObject.mtool_gen_cncjob`) consumes a dict:
`{1: {'tooldia': <float>, 'data': {<all tools_mill_* keys>}, 'solid_geometry': <geom>}}`.
The builder seeds `data` from the geometry's own options (so every required key exists with a valid default — including `tools_mill_offset_type` which defaults to integer `0` → zero offset, avoiding the milling-only `'custom'` UI branch) and overrides only the laser-relevant keys.

- [ ] **Step 1: Write the failing test**

Create `tests_laser/test_tools_dict.py`:

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from appPlugins import laser_core

# a stand-in for GeometryObject.obj_options: must contain the mill keys with valid defaults
geo_options = {
    "tools_mill_offset_type": 0,
    "tools_mill_cutz": -2.0, "tools_mill_travelz": 2.0,
    "tools_mill_feedrate": 120, "tools_mill_feedrate_z": 60, "tools_mill_feedrate_rapid": 1500,
    "tools_mill_multidepth": True, "tools_mill_depthperpass": 0.8,
    "tools_mill_extracut": False, "tools_mill_extracut_length": 0.1,
    "tools_mill_toolchange": False, "tools_mill_toolchangez": 15, "tools_mill_toolchangexy": "",
    "tools_mill_startz": None, "tools_mill_endz": 0.5,
    "tools_mill_spindlespeed": 0, "tools_mill_dwell": False, "tools_mill_dwelltime": 1,
    "tools_mill_ppname_g": "default", "tools_mill_min_power": 0, "tools_mill_laser_on": "M3",
}

# power set in FlatCAM -> spindlespeed = 70% of 1000 = 700, air assist on, M4
params = dict(power_in_app=True, power_pct=70, power_max=1000, speed=300,
              air_assist=True, laser_mode="M4")
td = laser_core.build_laser_tools_dict(geo_options, params, solid_geometry=["GEOM"])
data = td[1]['data']
assert td[1]['solid_geometry'] == ["GEOM"]
assert data['tools_mill_ppname_g'] == 'GRBL_laser_air_assist', data['tools_mill_ppname_g']
assert data['tools_mill_feedrate'] == 300
assert data['tools_mill_spindlespeed'] == 700, data['tools_mill_spindlespeed']
assert data['tools_mill_laser_on'] == 'M4'
assert data['tools_mill_multidepth'] is False           # laser never uses Z multidepth
assert data['tools_mill_offset_type'] == 0              # zero offset preserved

# power set in LaserGRBL -> spindlespeed empty so preprocessor emits bare M4/M3
params2 = dict(power_in_app=False, power_pct=70, power_max=1000, speed=250,
               air_assist=False, laser_mode="M3")
td2 = laser_core.build_laser_tools_dict(geo_options, params2, solid_geometry=["G"])
data2 = td2[1]['data']
assert data2['tools_mill_spindlespeed'] == '', repr(data2['tools_mill_spindlespeed'])
assert data2['tools_mill_ppname_g'] == 'GRBL_laser', data2['tools_mill_ppname_g']
assert data2['tools_mill_feedrate'] == 250

print("test_tools_dict OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-build\Scripts\python tests_laser\test_tools_dict.py`
Expected: FAIL — `AttributeError: module 'appPlugins.laser_core' has no attribute 'build_laser_tools_dict'`

- [ ] **Step 3: Write minimal implementation**

Append to `appPlugins/laser_core.py`:

```python
from copy import deepcopy

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-build\Scripts\python tests_laser\test_tools_dict.py`
Expected: `test_tools_dict OK`

- [ ] **Step 5: Commit**

```
git add appPlugins/laser_core.py
git commit -m "Add laser tools-dict builder"
```

---

## Task 4: Multi-pass G-code repetition

**Files:**
- Modify: `appPlugins/laser_core.py`
- Test: `tests_laser/test_passes.py`

Laser preprocessors skip Z multi-depth, so multiple passes = re-tracing the cut body.
`mtool_gen_cncjob` stores per-tool G-code in `cncjob.tools[uid]['gcode']`. The cut body is
everything between the air-assist/header (which ends at the first laser-on `M3`/`M4` line)
and the final framing (`M9`/`M5`/`G0 ...` home). `repeat_cut_passes` duplicates the body
between the first laser-on line and the last laser-off (`M5`) line.

If the markers are not found, it returns the original G-code unchanged and signals failure,
so the caller can honestly fall back to a single pass (see Task 6, Step on passes).

- [ ] **Step 1: Write the failing test**

Create `tests_laser/test_passes.py`:

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from appPlugins import laser_core

gcode = "\n".join([
    "G21", "G90", "M8 (air assist ON)",   # header
    "M4 S700",                              # first laser ON
    "G1 X0 Y0 F300", "G1 X10 Y0 F300",      # cut body
    "M5",                                   # laser OFF
    "M9 (air assist OFF)", "G0 X0 Y0",      # footer
]) + "\n"

out, ok = laser_core.repeat_cut_passes(gcode, 3)
assert ok is True
# the cut move line should now appear 3 times
assert out.count("G1 X10 Y0 F300") == 3, out.count("G1 X10 Y0 F300")
# header and footer appear once
assert out.count("M8 (air assist ON)") == 1
assert out.count("M9 (air assist OFF)") == 1
# n=1 is a no-op
same, ok1 = laser_core.repeat_cut_passes(gcode, 1)
assert same == gcode and ok1 is True

# missing markers -> unchanged + ok False
bad = "G21\nG90\nG0 X0 Y0\n"
unchanged, ok2 = laser_core.repeat_cut_passes(bad, 3)
assert unchanged == bad and ok2 is False

print("test_passes OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv-build\Scripts\python tests_laser\test_passes.py`
Expected: FAIL — `AttributeError: ... has no attribute 'repeat_cut_passes'`

- [ ] **Step 3: Write minimal implementation**

Append to `appPlugins/laser_core.py`:

```python
import re

_LASER_ON_RE = re.compile(r'^\s*M[34]\b')
_LASER_OFF_RE = re.compile(r'^\s*M5\b')


def repeat_cut_passes(gcode, n_passes):
    """Repeat the cut body of a laser tool's G-code n_passes times.

    Returns (new_gcode, ok). ok is False (and gcode is returned unchanged) when the
    laser-on / laser-off seam markers cannot be located, so the caller can fall back to
    a single pass honestly.
    """
    if n_passes is None or int(n_passes) <= 1:
        return gcode, True

    lines = gcode.splitlines()
    first_on = next((i for i, ln in enumerate(lines) if _LASER_ON_RE.match(ln)), None)
    last_off = next((i for i in range(len(lines) - 1, -1, -1) if _LASER_OFF_RE.match(lines[i])), None)
    if first_on is None or last_off is None or last_off <= first_on:
        return gcode, False

    header = lines[:first_on]
    body = lines[first_on:last_off + 1]   # inclusive of laser-on .. laser-off
    footer = lines[last_off + 1:]

    repeated = []
    for _ in range(int(n_passes)):
        repeated.extend(body)
    new_lines = header + repeated + footer
    return "\n".join(new_lines) + ("\n" if gcode.endswith("\n") else ""), True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv-build\Scripts\python tests_laser\test_passes.py`
Expected: `test_passes OK`

- [ ] **Step 5: Commit**

```
git add appPlugins/laser_core.py
git commit -m "Add laser multi-pass G-code repetition"
```

---

## Task 5: ToolLaser plugin — panel + registration

**Files:**
- Create: `appPlugins/ToolLaser.py`
- Modify: `appPlugins/__init__.py` (add export near the other tool imports, ~line 40)
- Modify: `appMain.py` (instantiate alongside other `self.x_tool = X(self)` lines, ~lines 1650-1770; and add to the plugins menu/toolbar registration the same way a sibling tool is added)
- Test: `tests_laser/test_register.py`

Follow the structure of an existing simple `AppTool` (e.g. `appPlugins/ToolFilm.py`) for the
`__init__`, `install`, `run`, `set_tool_ui`, and `build_ui` conventions. Use `GUIElements`
widgets (`FCComboBox`, `FCSpinner`, `FCDoubleSpinner`, `FCCheckBox`, `RadioSet`, `FCButton`,
`FCLabel`, `GLay`) — never raw Qt widgets.

- [ ] **Step 1: Read a reference plugin**

Read `appPlugins/ToolFilm.py` start-to-end of its `__init__`, `install`, `run`, and
`build_ui`/`set_tool_ui` methods, and read how `ToolFilm` is imported in
`appPlugins/__init__.py` and instantiated + registered in `appMain.py` (search `ToolFilm`).
Mirror those exact patterns. (No code to write in this step.)

- [ ] **Step 2: Create the plugin skeleton + panel**

Create `appPlugins/ToolLaser.py`:

```python
# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# File Author: Marius Adrian Stanciu (c)                   #
# Date: 6/11/2026                                          #
# MIT Licence                                              #
# ##########################################################

import os
from PyQt6 import QtWidgets
from appTool import AppTool
from appGUI.GUIElements import (
    FCComboBox, FCSpinner, FCDoubleSpinner, FCCheckBox, RadioSet, FCButton, FCLabel, GLay
)
from appPlugins import laser_core

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext


class ToolLaser(AppTool):

    def __init__(self, app):
        AppTool.__init__(self, app)
        self.app = app
        self.decimals = self.app.decimals
        self.pluginName = _("Laser")

        self.presets = laser_core.load_laser_presets(
            os.path.join(self.app.app_home, 'assets', 'resources', 'laser_presets.json'))
        self.preset_by_name = {p['name']: p for p in self.presets}

        # the generated laser CNCJob object, used by the export button
        self.laser_cncjob = None

        self.layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.layout)
        self._build_panel()
        self._connect_signals()

    def _build_panel(self):
        title = FCLabel('%s' % _("Laser"), bold=True)
        self.layout.addWidget(title)

        grid = GLay(v_spacing=5, h_spacing=3)
        self.layout.addLayout(grid)

        # Source object
        grid.addWidget(FCLabel('%s:' % _("Source object")), 0, 0)
        self.object_combo = FCComboBox()
        self.object_combo.setModel(self.app.collection)
        self.object_combo.setRootModelIndex(self.app.collection.index(0, 0, None))
        self.object_combo.is_last = True
        # show Gerber + Geometry objects
        self.object_combo.obj_type = "gerber_geometry"
        grid.addWidget(self.object_combo, 0, 1)

        # Material preset
        grid.addWidget(FCLabel('%s:' % _("Material preset")), 2, 0)
        self.preset_combo = FCComboBox()
        self.preset_combo.addItems([p['name'] for p in self.presets])
        grid.addWidget(self.preset_combo, 2, 1)

        # Power source
        grid.addWidget(FCLabel('%s:' % _("Power source")), 4, 0)
        self.power_src_radio = RadioSet([
            {'label': _('Set in FlatCAM'), 'value': 'app'},
            {'label': _('Set in LaserGRBL'), 'value': 'sender'},
        ], orientation='vertical')
        grid.addWidget(self.power_src_radio, 4, 1)

        # Power %
        self.power_label = FCLabel('%s:' % _("Power"))
        grid.addWidget(self.power_label, 6, 0)
        self.power_spinner = FCSpinner()
        self.power_spinner.set_range(0, 100)
        self.power_spinner.set_value(100)
        grid.addWidget(self.power_spinner, 6, 1)

        # Speed
        grid.addWidget(FCLabel('%s:' % _("Speed (mm/min)")), 8, 0)
        self.speed_spinner = FCDoubleSpinner()
        self.speed_spinner.set_range(1, 100000)
        self.speed_spinner.set_value(300)
        grid.addWidget(self.speed_spinner, 8, 1)

        # Passes
        grid.addWidget(FCLabel('%s:' % _("Passes")), 10, 0)
        self.passes_spinner = FCSpinner()
        self.passes_spinner.set_range(1, 100)
        self.passes_spinner.set_value(1)
        grid.addWidget(self.passes_spinner, 10, 1)

        # Air assist
        self.air_cb = FCCheckBox('%s' % _("Air assist"))
        grid.addWidget(self.air_cb, 12, 0, 1, 2)

        # Laser mode
        grid.addWidget(FCLabel('%s:' % _("Laser mode")), 14, 0)
        self.mode_radio = RadioSet([
            {'label': _('Dynamic (M4)'), 'value': 'M4'},
            {'label': _('Constant (M3)'), 'value': 'M3'},
        ])
        grid.addWidget(self.mode_radio, 14, 1)

        self.generate_btn = FCButton('%s' % _("Generate Laser Job"))
        self.layout.addWidget(self.generate_btn)
        self.export_btn = FCButton('%s' % _("Export for LaserGRBL"))
        self.layout.addWidget(self.export_btn)
        self.layout.addStretch()

    def _connect_signals(self):
        self.preset_combo.currentIndexChanged.connect(self.on_preset_change)
        self.power_src_radio.activated_custom.connect(self.on_power_source_change)
        self.generate_btn.clicked.connect(self.on_generate)
        self.export_btn.clicked.connect(self.on_export)

    def install(self, icon=None, separator=None, **kwargs):
        AppTool.install(self, icon, separator, shortcut=None, **kwargs)

    def run(self, toggle=True):
        self.app.defaults.report_usage("ToolLaser()")
        if toggle:
            if self.app.ui.splitter.sizes()[0] == 0:
                self.app.ui.splitter.setSizes([1, 1])
        AppTool.run(self)
        self.set_tool_ui()
        self.app.ui.notebook.setTabText(2, _("Laser"))

    def set_tool_ui(self):
        self.preset_combo.set_value(self.app.options['tools_laser_preset'])
        self.power_src_radio.set_value('app' if self.app.options['tools_laser_power_in_app'] else 'sender')
        self.mode_radio.set_value(self.app.options['tools_laser_mode'])
        self.air_cb.set_value(self.app.options['tools_laser_air_assist'])
        self.on_preset_change()
        self.on_power_source_change()

    def on_preset_change(self):
        name = self.preset_combo.get_value()
        if name == 'Custom' or name not in self.preset_by_name:
            return
        p = self.preset_by_name[name]
        self.power_spinner.set_value(p['power_pct'])
        self.speed_spinner.set_value(p['speed'])
        self.passes_spinner.set_value(p['passes'])
        self.air_cb.set_value(p['air_assist'])
        self.mode_radio.set_value(p['laser_mode'])

    def on_power_source_change(self, *args):
        in_app = self.power_src_radio.get_value() == 'app'
        # visible but disabled when LaserGRBL controls power
        self.power_spinner.setDisabled(not in_app)

    def on_generate(self):
        pass  # implemented in Task 6

    def on_export(self):
        pass  # implemented in Task 7
```

NOTE on the object combo: if `obj_type = "gerber_geometry"` is not a supported filter in this
codebase, read how `ToolFilm`/`ToolMilling` set `object_combo.obj_type` and use the matching
convention (some plugins set it to a single kind and filter in code). Match the existing API
exactly; do not invent a value.

- [ ] **Step 3: Export from the package**

In `appPlugins/__init__.py`, near the other imports (e.g. after the `ToolFilm` import around line 7), add:

```python
from appPlugins.ToolLaser import ToolLaser
```

- [ ] **Step 4: Instantiate and register in appMain**

In `appMain.py`, find where a sibling tool (e.g. `self.film_tool = Film(self)`) is created and
where its `.install(...)` is called for the Plugins menu. Add the analogous two integrations:

```python
        self.laser_tool = ToolLaser(self)
        self.laser_tool.install(icon=QtGui.QIcon(self.resource_location + '/laser16.png'),
                                pos=self.ui.menutool)
```

Match the exact `install(...)` signature and menu target used by the sibling tool you copied;
if siblings pass no icon, pass none. (Reuse an existing icon path if `laser16.png` does not
exist — pick any existing tool icon in `assets/resources/` to avoid a missing-file issue.)

- [ ] **Step 5: Write the registration test**

Create `tests_laser/test_register.py`:

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# import-level smoke test: the modules import without Qt instantiation errors
import importlib
m = importlib.import_module('appPlugins.ToolLaser')
assert hasattr(m, 'ToolLaser')
import appPlugins
assert hasattr(appPlugins, 'ToolLaser')
print("test_register OK")
```

- [ ] **Step 6: Run the import test**

Run: `.venv-build\Scripts\python tests_laser\test_register.py`
Expected: `test_register OK`

- [ ] **Step 7: Launch the app and confirm the panel opens**

Run: `.venv-build\Scripts\python flatcam.py` (GUI). Open Menu → Plugins → Laser.
Expected: the Laser panel appears with all fields; selecting a preset fills the fields;
switching Power source to "Set in LaserGRBL" greys out the Power field. Close the app.

- [ ] **Step 8: Commit**

```
git add appPlugins/ToolLaser.py appPlugins/__init__.py appMain.py
git commit -m "Add ToolLaser plugin panel and registration"
```

---

## Task 6: Wire generation (source prep + generate + passes)

**Files:**
- Modify: `appPlugins/ToolLaser.py` (replace the `on_generate` stub)
- Test: `tests_laser/test_e2e_generate.py`

- [ ] **Step 1: Implement source preparation + generation**

Replace `on_generate` in `appPlugins/ToolLaser.py` with:

```python
    def _resolve_geometry(self, source_obj):
        """Return a GeometryObject to trace. Gerber -> internal follow (centerline)."""
        if source_obj.kind == 'geometry':
            return source_obj
        if source_obj.kind == 'gerber':
            trace_name = '%s_laser_trace' % source_obj.obj_options['name']
            source_obj.follow_geo(outname=trace_name)
            geo = self.app.collection.get_by_name(trace_name)
            if geo is None:
                self.app.inform.emit('[ERROR_NOTCL] %s' % _("Could not create the laser trace geometry."))
            return geo
        self.app.inform.emit('[ERROR_NOTCL] %s' % _("Select a Gerber or Geometry object."))
        return None

    def _collect_params(self):
        return dict(
            power_in_app=(self.power_src_radio.get_value() == 'app'),
            power_pct=self.power_spinner.get_value(),
            power_max=float(self.app.options['tools_laser_power_max']),
            speed=self.speed_spinner.get_value(),
            air_assist=self.air_cb.get_value(),
            laser_mode=self.mode_radio.get_value(),
        )

    def on_generate(self):
        obj_name = self.object_combo.get_value()
        source_obj = self.app.collection.get_by_name(obj_name)
        if source_obj is None:
            self.app.inform.emit('[ERROR_NOTCL] %s: %s' % (_("Could not retrieve object"), obj_name))
            return

        geo = self._resolve_geometry(source_obj)
        if geo is None:
            return

        params = self._collect_params()
        n_passes = self.passes_spinner.get_value()
        out_name = '%s_laser' % source_obj.obj_options['name']

        tools_dict = laser_core.build_laser_tools_dict(geo.obj_options, params, geo.solid_geometry)

        def after(new_cncjob):
            # repeat passes in the generated per-tool gcode
            if n_passes > 1 and new_cncjob is not None:
                ok_any = False
                for uid in new_cncjob.tools:
                    g = new_cncjob.tools[uid].get('gcode', '')
                    new_g, ok = laser_core.repeat_cut_passes(g, n_passes)
                    new_cncjob.tools[uid]['gcode'] = new_g
                    ok_any = ok_any or ok
                if not ok_any:
                    self.app.inform.emit('[WARNING_NOTCL] %s' % _(
                        "Could not apply multiple passes; generated a single pass. "
                        "You can set passes in LaserGRBL instead."))
            self.laser_cncjob = new_cncjob
            self.app.inform.emit('[success] %s' % _("Laser job generated. Use 'Export for LaserGRBL'."))

        # generate; mtool_gen_cncjob creates the object asynchronously, so fetch by name after
        geo.mtool_gen_cncjob(outname=out_name, tools_dict=tools_dict, plot=True, use_thread=False)
        new_cncjob = self.app.collection.get_by_name(out_name)
        after(new_cncjob)
```

NOTE: `mtool_gen_cncjob` may run on a worker thread when `use_thread=True`. Pass
`use_thread=False` so the object exists immediately after the call (matching the synchronous
fetch above). Verify this signature in `GeometryObject.mtool_gen_cncjob` (it accepts
`use_thread`); if the object is still not present synchronously, connect to
`self.app.app_obj.new_object_added`-style signal as the sibling milling code does and move the
`after()` work there.

- [ ] **Step 2: Write the end-to-end generation test**

Create `tests_laser/square.gbr`:

```
%FSLAX26Y26*%
%MOMM*%
%ADD10C,0.200000*%
D10*
X1000000Y1000000D02*
X9000000Y1000000D01*
X9000000Y9000000D01*
X1000000Y9000000D01*
X1000000Y1000000D01*
M02*
```

Create `tests_laser/laser_e2e.FlatScript`:

```
new
open_gerber N:/Projects/Github/flatcam-home/tests_laser/square.gbr -outname sq
```

Create `tests_laser/test_e2e_generate.py` that launches the app with a script that opens the
Gerber, then drives the plugin in-process via the app instance is not trivial from Tcl; instead
this test runs a focused headless driver:

```python
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# Build the laser tool gcode path through the real engine using a scripted app run.
# We reuse FlatCAM's Tcl: open gerber -> follow -> cncjob with the laser preprocessor,
# then write gcode, asserting laser markers. This exercises the same engine the plugin uses.
script = r'''
new
open_gerber {root}/tests_laser/square.gbr -outname sq
follow sq -outname sqf
cncjob sqf -dia 0.1 -feedrate 300 -las_power 700 -las_min_pwr 0 -pp GRBL_laser_air_assist -outname sqjob
write_gcode sqjob {root}/tests_laser/e2e_out.gcode
quit_app
'''.replace('{root}', ROOT.replace('\\', '/'))

script_path = os.path.join(ROOT, 'tests_laser', 'e2e.FlatScript')
open(script_path, 'w').write(script)

out = os.path.join(ROOT, 'tests_laser', 'e2e_out.gcode')
if os.path.exists(out):
    os.remove(out)

import subprocess, time
py = os.path.join(ROOT, '.venv-build', 'Scripts', 'python.exe')
p = subprocess.Popen([py, 'flatcam.py', script_path], cwd=ROOT)
deadline = time.time() + 150
while time.time() < deadline and not os.path.exists(out):
    time.sleep(3)
try:
    p.terminate()
except Exception:
    pass

assert os.path.exists(out), "no gcode produced"
g = open(out).read()
assert 'M8 (air assist ON)' in g, "air assist start missing"
assert 'M9 (air assist OFF)' in g, "air assist end missing"
assert ('M4 S700' in g) or ('M3 S700' in g), "laser power line missing"
print("test_e2e_generate OK")
```

(This validates the engine + preprocessor path the plugin relies on. The follow→laser cncjob
chain is exactly what `on_generate` triggers internally.)

- [ ] **Step 3: Run the end-to-end test**

Run: `.venv-build\Scripts\python tests_laser\test_e2e_generate.py`
Expected: `test_e2e_generate OK`

If it fails because the `follow` Tcl command name differs, run
`.venv-build\Scripts\python -c "import tclCommands; print([n for n in dir(tclCommands) if 'ollow' in n])"`
and use the correct command alias.

- [ ] **Step 4: Manual GUI check**

Run `.venv-build\Scripts\python flatcam.py`, open the `square.gbr`, open the Laser panel,
select the Gerber, choose "PCB — surface mark", click **Generate Laser Job**. Confirm a
`*_laser` CNCJob appears in the project tree and plots. Close the app.

- [ ] **Step 5: Commit**

```
git add appPlugins/ToolLaser.py
git commit -m "Wire laser job generation (Gerber follow + engine + passes)"
```

---

## Task 7: Export for LaserGRBL

**Files:**
- Modify: `appPlugins/ToolLaser.py` (replace the `on_export` stub)

- [ ] **Step 1: Implement export**

Replace `on_export` in `appPlugins/ToolLaser.py` with:

```python
    def on_export(self):
        if self.laser_cncjob is None:
            self.app.inform.emit('[WARNING_NOTCL] %s' % _("Generate a laser job first."))
            return

        last_dir = self.app.options['tools_laser_last_export_folder'] or self.app.get_last_folder()
        filename, _filter = QtWidgets.QFileDialog.getSaveFileName(
            caption=_("Export G-Code for LaserGRBL"),
            directory=os.path.join(last_dir, '%s.nc' % self.laser_cncjob.obj_options['name']),
            filter="G-Code Files (*.nc *.gcode *.ngc);;All Files (*.*)")
        if not filename:
            return

        self.laser_cncjob.export_gcode(filename=filename)
        self.app.options['tools_laser_last_export_folder'] = os.path.dirname(filename)
        self.app.inform.emit('[success] %s: %s' % (_("Laser G-Code saved"), filename))
```

NOTE: confirm `CNCJobObject.export_gcode(filename=...)` writes directly to the path (it does in
this codebase). If it requires more args, read `on_exportgcode_button_click` (CNCJobObject.py
~line 695) and mirror the call it makes. Confirm `self.app.get_last_folder()` exists; if not,
use `self.app.options['global_last_folder']` or `''`.

- [ ] **Step 2: Manual GUI check (export is inherently GUI/file-dialog)**

Run `.venv-build\Scripts\python flatcam.py`, generate a laser job (Task 6), click
**Export for LaserGRBL**, save as `test.nc`. Open the saved file in a text editor and confirm
it begins with the air-assist header and contains the laser commands. Close the app.

- [ ] **Step 3: Commit**

```
git add appPlugins/ToolLaser.py
git commit -m "Add Export for LaserGRBL to the laser plugin"
```

---

## Task 8: Build integration, docs, CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `dist/FlatCAM_Evo/_internal/...` (copy, no commit)

- [ ] **Step 1: Add CHANGELOG entry**

In `CHANGELOG.md`, under the existing `10.06.2026` block (or a new `11.06.2026` block at the
top below the header), add:

```
11.06.2026

- added a new "Laser" plugin aimed at new laser users (CNC 3018 + diode laser with air assist, driven by LaserGRBL): pick a Gerber or Geometry object, choose a material preset (or set Power %/Speed/Passes), and generate a laser job, then export a .nc file ready for LaserGRBL
- the Laser plugin speaks laser vocabulary only (no Z-depth, tool diameter, offset, or roughing); Gerber sources are auto-traced to their centerline (follow) so PCB work needs no manual isolation
- power can be baked into the G-code by FlatCAM (Power %) or left for LaserGRBL to control (bare M3/M4)
- material presets are stored in assets/resources/laser_presets.json and are user-editable
```

- [ ] **Step 2: Refresh the packaged build (no rebuild needed for data/py files)**

The plugin is plain Python plus a JSON asset, both inside already-bundled trees. To update the
existing dist without a full rebuild, copy the new files in:

```
Copy-Item appPlugins\ToolLaser.py dist\FlatCAM_Evo\_internal\appPlugins\ToolLaser.py -Force
Copy-Item appPlugins\laser_core.py dist\FlatCAM_Evo\_internal\appPlugins\laser_core.py -Force
Copy-Item assets\resources\laser_presets.json dist\FlatCAM_Evo\_internal\assets\resources\laser_presets.json -Force
```

(A clean `.\build_windows.ps1` also bundles them automatically.)

- [ ] **Step 3: Smoke-test the packaged exe**

Run `dist\FlatCAM_Evo\FlatCAM_Evo.exe`, open the Laser panel, confirm presets load. Close it.

- [ ] **Step 4: Commit**

```
git add CHANGELOG.md
git commit -m "Document the Laser plugin in CHANGELOG"
```

---

## Self-review against the spec

- Source = Gerber or Geometry; Excellon excluded → Tasks 5/6 (`_resolve_geometry` handles
  gerber/geometry, rejects others). ✓
- PCB-easy via internal follow → Task 6 `_resolve_geometry`. ✓
- Laser vocabulary, no milling fields → Task 5 panel. ✓
- Material presets, user-editable JSON, PCB first/default → Tasks 1, 2, 5. ✓
- Power source FlatCAM vs LaserGRBL, % field greys out → Tasks 3 (`build_laser_tools_dict`
  empty spindlespeed) + 5 (`on_power_source_change`). ✓
- Power % → S mapping with configurable max ($30 default 1000) → Task 1 option + Task 3. ✓
- Multi-pass with honest single-pass fallback → Task 4 + Task 6 fallback inform. ✓
- Air assist toggles preprocessor → Task 3. ✓
- Laser mode M3/M4 → Tasks 3, 5. ✓
- Generate via existing engine; Export via existing export_gcode → Tasks 6, 7. ✓
- Build picks up assets automatically → Task 8. ✓
- Tests for presets, tools-dict, passes, registration, e2e → Tasks 2,3,4,5,6. ✓

Open risk carried from spec: exact `object_combo.obj_type` filter value and the
synchronous-vs-threaded behavior of `mtool_gen_cncjob` — both flagged inline in Task 5/6 with
the concrete fallback (match sibling plugin API; use the new-object signal if not synchronous).
