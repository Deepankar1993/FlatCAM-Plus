# Laser Plugin — Design

Date: 2026-06-11
Branch: `Beta_8.996`
Status: Approved design (pending spec review)

## Problem

FlatCAM's CNCJob/Milling UI speaks milling vocabulary — "Tools Table", "Roughing",
"Offset", "Dia", "Travelled distance", Z cut depths, tool shapes. A new laser user
(CNC 3018 + diode laser module with air assist, driving the machine through the
**LaserGRBL** sender) has to mentally translate all of that, has no idea what power and
speed values to use, sees many fields that do not apply to a laser, and has to discover
which preprocessor to pick and how to export a file LaserGRBL can run.

Goal: a single, laser-first entry point that hides milling jargon, offers material
presets, supports the user's three uses (cutting thin material, engraving/marking, PCB
work), and makes the **PCB path the easiest**, ending in a file ready for LaserGRBL.

## Non-goals (v1)

- Photo/raster image engraving (greyscale → variable-power raster). Much larger
  image-processing feature; the separate, currently-broken `ToolImage` plugin is unrelated.
- Replacing or restyling the existing Milling / CNCJob panels. Those keep working
  unchanged for milling users.
- Auto-launching LaserGRBL. Export writes a file; the user opens it in LaserGRBL.
- Editing/added preprocessors beyond the existing `GRBL_laser_air_assist`.

## User-facing design

### Entry point

New plugin `appPlugins/ToolLaser.py`, class `ToolLaser(AppTool)`, `pluginName = "Laser"`.
Registered the same way every other plugin is:
- instantiated in `App.__init__` (appMain.py, alongside the other `self.x_tool = X(self)` lines),
- exported from `appPlugins/__init__.py`,
- given a menu action via the plugin's `install()` (Plugins menu) and a toolbar entry.

It reuses the existing app-level Beginner/Advanced toggle (`global_app_level`) the same way
other plugins do, but even the Advanced view stays laser-only in vocabulary.

### Panel layout

```
┌─ Laser ──────────────────────────────┐
 Source object:  [ door_Edge_Cuts.gbr ▼ ]   (Gerber or Geometry)

 Material preset: [ PCB — surface mark  ▼ ]

   Power source:  (•) Set in FlatCAM   [ 100 ] %
                  ( ) Set in LaserGRBL
   Speed          [ 300 ] mm/min
   Passes         [   1 ]
   Air assist     [✓]
   Laser mode     (•) Dynamic (M4)   ( ) Constant (M3)

 [ Generate Laser Job ]
 [ Export for LaserGRBL ]
└───────────────────────────────────────┘
```

Vocabulary rules: no Z-depth, tool diameter, offset, roughing, or tool-shape fields
anywhere in this panel.

### Field semantics

- **Source object**: a Gerber or a Geometry object from the project. (Excellon is out of
  scope for v1 — laser drilling is not a real use.)
- **Material preset**: selecting a preset fills Power/Speed/Passes/Air assist/Laser mode.
  A `Custom` entry leaves fields editable without imposing values. Changing any field after
  selecting a preset is allowed (it does not snap back).
- **Power source**:
  - *Set in FlatCAM*: the Power % field is active. Emitted laser power
    `S = round(power_pct / 100 * power_max)`, where `power_max` defaults to **1000**
    (GRBL `$30`) and is a plugin option (`tools_laser_power_max`).
  - *Set in LaserGRBL*: the Power % field is **visible but disabled** (shown for reference).
    The job is generated with **no S value** — the preprocessor emits a bare `M3`/`M4` and
    `M5` — so LaserGRBL's own power control drives intensity. This works because the
    `GRBL_laser_air_assist` preprocessor already emits the bare command when no spindle
    speed is set (`down_code`/`spindle_code`: `if p.spindlespeed: 'M3 S..' else 'M3'`).
- **Speed**: feedrate in current units/min (`feedrate`).
- **Passes**: how many times the toolpath is repeated (laser has no Z, so multiple passes =
  re-tracing the same path). `1` for engraving/marking, more for cutting.
- **Air assist**: chooses the preprocessor — checked = `GRBL_laser_air_assist`,
  unchecked = `GRBL_laser`. Both already exist.
- **Laser mode**: `M4` (dynamic power, recommended for engraving) vs `M3` (constant). Sets
  `laser_on` in the tool data.

### Material presets

Shipped as a user-editable JSON at `assets/resources/laser_presets.json`, loaded at plugin
init. If the file is missing or malformed, fall back to a built-in copy of the same list and
log a warning (never crash).

Each preset:
```json
{
  "name": "PCB — surface mark",
  "power_pct": 35,
  "speed": 600,
  "passes": 1,
  "air_assist": true,
  "laser_mode": "M4"
}
```

Starter set (conservative starting points; UI/README state "always test on scrap first"):
- `PCB — surface mark`
- `Plywood 3 mm — cut`
- `Cardstock — cut`
- `Vinyl — cut`
- `Wood — engrave`
- `Acrylic — engrave`
- `Custom`

The PCB preset is listed first so it is the default selection — supporting "really easy
for PCB".

## Internal design

### Source handling — PCB made easy

`prepare_geometry(source_obj) -> GeometryObject`:
- If `source_obj.kind == 'geometry'`: use it directly.
- If `source_obj.kind == 'gerber'`: build the **follow (centerline) geometry** internally via
  the existing `GerberObject.follow_geo(outname=<name>_laser_trace)`, and use that. This is
  the correct laser action (trace the line, do not route around it with a tool diameter) and
  removes the manual isolation step — the core "easy for PCB" win. Done automatically, no
  per-job prompt.
- Otherwise: inform the user the object type is unsupported and stop.

### Generate

`generate()`:
1. Resolve and prepare the geometry (above).
2. Build a single-tool `tools_dict` of the shape the milling engine expects:
   ```
   { 1: { 'tooldia': <small marker dia, e.g. 0.1>,
          'data': { ...geometry defaults...,
                    'tools_mill_ppname_g': 'GRBL_laser_air_assist' | 'GRBL_laser',
                    'tools_mill_feedrate': <speed>,
                    'tools_mill_spindlespeed': <S or '' for LaserGRBL-controlled>,
                    'tools_mill_laser_on': 'M4' | 'M3',
                    'tools_mill_min_power': 0,
                    'tools_mill_multidepth': False,
                    ... (Z values present but ignored by laser preprocessors) },
          'solid_geometry': <geometry.solid_geometry> } }
   ```
   Seed `data` from the geometry object's own options so all required keys exist, then
   override the laser-relevant ones. This avoids missing-key crashes (the same class of bug
   fixed in the legacy-project work).
3. Call `geo_obj.mtool_gen_cncjob(outname=<name>_laser, tools_dict=tools_dict)`. The result
   is a normal CNCJob object that plots and behaves like any other.
4. **Passes > 1**: laser preprocessors skip Z multi-depth, so passes are implemented by
   repeating the per-tool toolpath body N times in the generated G-code. This is the one
   area of implementation risk. Plan: generate once, then in the CNCJob's gcode for the tool,
   duplicate the cutting body (between the start/end framing) N times. If a clean, verified
   implementation is not achievable in v1, ship with `passes = 1` only, disable the Passes
   field with a tooltip, and record a follow-up — **do not silently emit a single pass while
   showing N**.

### Export

`export_for_lasergrbl()`:
- Require a generated laser CNCJob (else inform and stop).
- Open a save dialog defaulting to the remembered laser export folder
  (`tools_laser_last_export_folder` option) and a `.nc` extension.
- Call the CNCJob's existing `export_gcode(filename=...)` path (same code the normal
  "Save CNC Code" button uses).
- Remember the folder; offer to open the containing folder afterwards.

### New options (defaults.py `factory_defaults`)

- `tools_laser_power_max`: 1000
- `tools_laser_power_pct`: 100
- `tools_laser_speed`: 300
- `tools_laser_passes`: 1
- `tools_laser_air_assist`: True
- `tools_laser_mode`: "M4"
- `tools_laser_power_in_app`: True   (False = controlled in LaserGRBL)
- `tools_laser_last_export_folder`: ""

These are namespaced `tools_laser_*` so they do not collide with milling options.

## Error handling

- Missing/invalid `laser_presets.json` → built-in fallback list + warning, no crash.
- Unsupported source object kind → user-facing inform message, no action.
- `follow_geo` producing empty geometry (e.g. an empty Gerber) → inform and stop.
- Generation reuses the existing, tested milling engine, so its own error paths apply.
- Export with no laser job present → inform and stop.

## Testing

Headless harness in the spirit of the preprocessor test (no GUI event loop required where
possible; a scripted app run where needed):

1. **Presets load**: `laser_presets.json` parses; the built-in fallback is used when the
   file is corrupt.
2. **Tools dict**: `generate()` builds a `tools_dict` with the laser preprocessor and the
   expected feedrate/spindlespeed for both power sources (FlatCAM bakes `S`, LaserGRBL emits
   none).
3. **End-to-end G-code**: load a small Gerber → `ToolLaser` generate → the CNCJob G-code
   contains the laser-on command (`M4`/`M3`), `M8`/`M9` when air assist is on, an `S` value
   only when power is set in FlatCAM, and N repeated passes when `passes = N`.
4. **Registration**: the plugin instantiates and registers without error; the panel builds.

No success claim without showing the harness output.

## Build/integration

- `assets/resources/laser_presets.json` is already inside the PyInstaller-bundled
  `assets/`, so the Windows build picks it up automatically.
- The new plugin is plain Python imported through `appPlugins/__init__.py`; no spec change
  needed beyond what already bundles `appPlugins`.

## Open risk

Multi-pass G-code generation (see Generate step 4) is the only part not backed by an
existing, proven code path. It is explicitly allowed to degrade to `passes = 1` for v1 with
a visible, honest UI state rather than silently misbehaving.
