# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

FlatCAM Evo (Beta 8.995) — a PyQt6 desktop application for preparing CNC jobs for PCB manufacturing. It parses Gerber/Excellon/SVG/DXF/PDF files and generates G-Code (e.g., isolation routing, drilling, paint/clear operations). Python >= 3.6 required (3.11 verified); Shapely >= 2.0.

## Commands

```sh
# Run the application (GUI app — launches a Qt window)
python flatcam.py

# Install Python dependencies (GDAL is not pip-installable on Windows; see requirements.txt header)
pip install -r requirements.txt

# Linux install (Ubuntu-like): installs system deps then the app
make install_dependencies
make install
```

There is **no test suite, no linter config, and no packaging config** (no tests/, pytest.ini, pyproject.toml, setup.py). Verification is manual: run the app. The default/PR branch is `mstanciu_Beta_8.995`, not master/main.

User settings live outside the repo (`%APPDATA%\FlatCAM` on Windows, `~/.FlatCAM` elsewhere) unless `config/configuration.txt` sets `portable=True`. Crash tracebacks are appended to `log.txt` in that folder (a custom `sys.excepthook` in flatcam.py swallows them from the console).

## Architecture

### Core layers

- **`appMain.py`** — the `App` class (~9000 lines): central hub holding the object collection, signals, tool instances, worker pool, and app lifecycle. Almost everything hangs off `self.app`.
- **`camlib.py`** — CAM engine: `Geometry` and `CNCjob` model classes, Shapely-based geometry algorithms, aperture macro handling. GUI-free.
- **`appObjects/`** — the object model. `FlatCAMObj` (in `AppObjectTemplate.py`) is the base for `GerberObject`, `ExcellonObject`, `GeometryObject`, `CNCJobObject`, `ScriptObject`, `DocumentObject`. Gerber/Excellon objects multiply-inherit from `FlatCAMObj` and their parser class. Objects are created through the factory `AppObject.new_object(kind, name, initialize)` which looks up the class in a `classdict` keyed by kind string ('gerber', 'excellon', 'geometry', 'cncjob', 'script', 'document') and copies app defaults prefixed `<kind>_` into the object's `obj_options`. `ObjectCollection` is the Qt tree model holding all project objects.
- **`appParsers/`** — file format parsers (Gerber, Excellon, SVG, DXF, PDF, HPGL2, fonts). Parsing logic lives here, not in appObjects.
- **`appGUI/`** — `MainGUI` (QMainWindow), custom widgets in `GUIElements.py` (FCEntry, FCButton, FCDoubleSpinner, RadioSet, …) — use these instead of raw Qt widgets for consistency — plus the preferences UI (`appGUI/preferences/`) and themes.
- **`appHandlers/`** — `appIO.py` (file open/save dispatch), `appEdit.py` (editor dispatch).
- **`appEditors/`** — interactive editors for each object type (GeoEditor, GerberEditor, ExcEditor, GCodeEditor, TextEditor), each with its own plugin subfolder.

### Plugin/tool system

All ~30 tools in `appPlugins/` (ToolIsolation, ToolDrilling, ToolPaint, ToolCutOut, …) inherit `AppTool` (`appTool.py`, a QWidget). They are instantiated directly in `App.__init__` (not discovered dynamically), register a menu action via `install()`, and `run()` swaps their UI into the notebook's plugin tab.

### Preprocessors (G-code post-processors)

`preprocessors/*.py` define G-code dialects (GRBL, Marlin, Roland, laser variants, …). Each subclasses `PreProc` or `AppPreProcTools` from `appPreProcessor.py`; the `ABCPreProcRegister` metaclass auto-registers every subclass into the global `preprocessors{}` dict at import time — defining the subclass is all that's needed. They implement methods like `start_code()`, `linear_code()`, `toolchange_code()`, `end_code()` receiving a parameter dict `p`.

### Tcl scripting

`tclCommands/` holds 70+ `TclCommand` subclasses (one file per command) powering the in-app Tcl shell. `tclCommands/__init__.py` auto-imports every module via `pkgutil.walk_packages`, so adding a new `TclCommandFoo.py` with the class is sufficient; `register_all_commands()` wires them up. Commands declare `aliases`, `arg_names`, `option_types`, `required`, and a structured `help` dict.

### Rendering: dual graphics backends

`App.use_3d_engine` switches between VisPy/OpenGL (`appGUI/PlotCanvas.py`, default) and a matplotlib legacy fallback (`PlotCanvasLegacy.py`). Objects never draw directly — they populate a `ShapeCollection` (VisPy) or `ShapeCollectionLegacy` (matplotlib). Rendering-affecting changes must handle both backends. `appGUI/VisPyPatches.py` monkeypatches VisPy at startup. The vendored `descartes/` package (Shapely→matplotlib patches) serves the legacy backend; `libs/` vendors qdarktheme.

### Threading

Never touch the GUI from a worker thread. Background work goes through `WorkerStack` (`appWorkerStack.py`) — a pool of `Worker` QObjects each in its own QThread — dispatched by emitting `app.worker_task` with `{'fcn': ..., 'params': [...]}`; results return to the GUI via Qt signals. `FCProcess`/`FCProcessContainer` (`appProcess.py`) are context managers tracking operation lifecycle for the status bar.

### Settings

`defaults.py` defines `factory_defaults` (hundreds of keys named `<kind>_<setting>` or `tools_<tool>_<setting>`) and the persistence layer. `obj_options` on each object is a `LoudDict` (`appCommon/Common.py`) — a dict with change callbacks that drive reactive UI updates. `appDatabase.py` is the tools database (ToolsDB2) for milling/drilling/NCC/paint tool definitions. Adding a new setting means touching `factory_defaults`, the preferences UI in `appGUI/preferences/`, and the consuming object/tool.

## Conventions

- Translatable user-facing strings are wrapped in `_('...')` (gettext via `appTranslation.py`); translations live in `locale/`.
- `CHANGELOG.md` is actively maintained with dated entries — significant changes are recorded there.
