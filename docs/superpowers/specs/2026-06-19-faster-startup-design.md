# Faster Startup — Design Spec

**Date:** 2026-06-19
**Component:** FlatCAM Evo (PyQt6 desktop CAM app)
**Status:** Approved for implementation planning

## Goal

Reduce cold-launch time of FlatCAM Evo (Beta 8.998) — the wall-clock from
`python flatcam.py` to a usable, fully-built main window — **without changing any
observable behavior**. Every tool, the Tcl shell, both graphics backends, and all
preprocessors must remain available exactly as they are today: no first-use delays,
no aggressive lazy construction of plugins / Tcl commands / preprocessors.

This work is **measurement-driven**. The candidate optimizations below are
**hypotheses** to be confirmed (or rejected) by before/after measurement. Nothing
in the "Architecture & Components" section is committed until a profile shows the
cost is real and a before/after delta shows the win. The deliverable includes a
repeatable startup-timing harness so each change can be justified with numbers.

## Why the current implementation is insufficient

Today's launch imports and constructs more than it needs before the window is
usable. The following are **verified facts from the code** (not yet quantified —
quantifying them is step one of the work):

1. **Both graphics backends are imported unconditionally, but only one is used.**
   - `appMain.py:61` `from appGUI.PlotCanvas import PlotCanvas` (VisPy/OpenGL).
   - `appMain.py:62` `from appGUI.PlotCanvasLegacy import PlotCanvasLegacy` (matplotlib).
   - `appMain.py:63` `from appGUI.PlotCanvas3d import PlotCanvas3d` (VisPy 3D).
   - At runtime exactly **one** 2D backend is chosen: `appMain.py:911` sets
     `self.use_3d_engine = True`, flipped to `False` only when
     `self.options["global_graphic_engine"] == '2D'` (`appMain.py:913-914`). The
     canvas is then built in `on_plotcanvas_setup()` which instantiates
     `PlotCanvas(self)` (`appMain.py:7350`) **or** `PlotCanvasLegacy(self)`
     (`appMain.py:7363`) — never both.
   - `PlotCanvasLegacy.py:27-39` imports matplotlib at module top: `from matplotlib
     import use as mpl_use`, `mpl_use("QtAgg")`, `from matplotlib.figure import
     Figure`, `from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg`,
     plus `matplotlib.lines.Line2D` and `matplotlib.offsetbox.AnchoredText`. It also
     pulls the vendored `descartes` via `PlotCanvasLegacy.py:15` `from
     descartes.patch import PolygonPatch`. **In the default VisPy configuration,
     importing matplotlib + its Qt backend + descartes is pure dead weight at
     startup.** (Importing matplotlib's pyplot/QtAgg stack is one of the heavier
     pure-Python import costs in a Qt app — hypothesis to confirm via
     `-X importtime`.)
   - `PlotCanvas3d` (`appMain.py:63`) is used **only** inside the user-triggered
     "3D Area" tab handler `on_3d_area()` at `appMain.py:5295`
     (`plotcanvas3d = PlotCanvas3d(plot_container_3d, self)`). It is never touched
     during normal startup, yet its module (and its VisPy scene/camera imports,
     `PlotCanvas3d.py:14-20`) is imported eagerly.

2. **Preprocessors are loaded by filesystem globbing + per-file source loading at
   startup.** `appMain.py:757` `self.preprocessors = load_preprocessors(self)`.
   `appPreProcessor.load_preprocessors()` (`appPreProcessor.py:148-160`) globs
   `app.data_path/preprocessors/*.py` and `preprocessors/*.py` and calls
   `SourceFileLoader('FlatCAMPostProcessor', file).load_module()` for **every**
   match. There are ~28 preprocessor modules (`preprocessors/*.py`). Each subclass
   registers itself into the global `preprocessors{}` dict at import time via the
   `ABCPreProcRegister` metaclass (`appPreProcessor.py:21-29`). **These must stay
   eagerly loaded** (locked decision: no first-use delay; the preprocessor combo
   boxes are populated at startup), so this is *not* a target for lazy loading —
   but it is a candidate to *measure* and possibly make cheaper (e.g. avoid
   double-globbing the same directory, or skip the redundant second search path
   when it resolves to the same files).

3. **70+ Tcl commands are imported at startup.** `tclCommands/__init__.py:7-79`
   explicitly imports 72 `TclCommandXxx` modules, then `tclCommands/__init__.py:88-90`
   *additionally* runs `pkgutil.walk_packages(__path__)` +
   `importlib.import_module(...)` over the whole package — re-walking modules that
   were already imported by the explicit list above. `register_all_commands()`
   (`tclCommands/__init__.py:93-128`) instantiates each command class. **The Tcl
   shell must remain fully available (locked decision), so the command set stays
   eager** — but the redundant `walk_packages` pass over already-imported modules
   is a candidate to *measure* and potentially remove (it is double work, not a
   behavior change).

4. **~35 plugins are instantiated eagerly during `App.__init__`.** They are
   imported via `from appPlugins import *` (`appMain.py:116`; the star pulls in the
   53 names listed in `appPlugins/__init__.py:1-53`) and constructed +
   `install()`-ed in the block at `appMain.py:1662-1832` (e.g.
   `self.isolation_tool = ToolIsolation(self)` at `appMain.py:1725`, collected into
   `self.app_plugins` at `appMain.py:1796`). **Per the locked decision these are NOT
   to be lazily constructed** (every tool must remain available with no first-use
   delay). This is listed only to scope it OUT as a target and to note it as a
   measurement baseline.

5. **No startup measurement exists in the tracked tree.** The existing perf harness
   `tests/perf_probe.py` measures **interactive hot paths** (open+parse+plot,
   mouse-move bursts, `info()` calls, plot-checkbox toggles — see its docstring at
   `tests/perf_probe.py:11-24`), not `App.__init__` startup time. There is no
   `python -X importtime` workflow and no cProfile of `App.__init__` checked in.

**Distinction from the recent perf commit.** Commit `9b2a02f7` ("Performance: fix
interactive sluggishness; fix Etch Compensation crash") addressed **interactive
lag during use** — `info()` `processEvents()` throttling, mouse-move hover
bounding-box test, HUD font caching, CNCJob `plot2()` de-dup, plot-checkbox
visibility flipping, inline buffer compute for selection/hover/tool collections,
and defaulting console logging to WARNING (`appMain.py:305-312`, gated by the
`FLATCAM_DEBUG` env var). **That was runtime responsiveness. This spec is about
cold-launch import/construction time** — a separate, complementary concern. The
`FLATCAM_DEBUG`/WARNING default from that commit is reused here as one already-shipped
startup win and as a measurement control.

## Decisions (locked)

- **Strategy: measure-first, safe wins only.** No optimization is committed without
  a before/after measurement that confirms (a) the cost is real and (b) the change
  reduces it. Candidates in this spec are **hypotheses** until measured.
- **Low-risk, invisible optimizations only.** Every tool, the Tcl shell, both
  graphics backends, and all preprocessors must remain available exactly as today.
  **No first-use delays. No aggressive lazy construction of plugins / Tcl commands /
  preprocessors.**
- **Allowed optimization classes:**
  - **(a) Defer importing the UNUSED 2D graphics backend.** Import the matplotlib
    `PlotCanvasLegacy` only when `global_graphic_engine == '2D'` (or on the
    Ctrl-modifier legacy fallback at `appMain.py:7345-7346`); import the VisPy
    `PlotCanvas` only when 3D is active. Defer `PlotCanvas3d` to `on_3d_area()`.
  - **(b) Lazy / deferred heavy imports not on the launch-critical path** (modules
    only reached by user actions, e.g. the 3D Area tab).
  - **(c) Removing redundant startup work** — e.g. the duplicate
    `walk_packages` pass over already-imported Tcl modules
    (`tclCommands/__init__.py:88-90`), double-globbing the same preprocessor
    directory, eagerly building hidden UI, or a duplicate plot/redraw pass at
    startup **if measurement finds one**.
- **Behavior parity is mandatory.** Output and feature availability must be
  byte/behavior-identical to today. Deferring an import must not change *whether* a
  feature works, only *when* its module is loaded — and the trigger must run before
  the feature is first used.
- **The timing harness is a first-class deliverable**: formalize `perf_probe.py`
  behind an env flag, plus document `python -X importtime` and a cProfile of
  `App.__init__` to produce a **ranked** breakdown.

## Architecture & Components

### A. Startup-timing harness (measurement infrastructure — build FIRST)

| Unit | Location | Responsibility |
|---|---|---|
| Startup mode for the perf harness | `tests/perf_probe.py` | Add an env-flag-gated **startup-timing** mode alongside the existing interactive probes. When `FLATCAM_PERF_STARTUP=1` (new env flag), the harness times `App(qapp=app_qt)` construction (wrap `tests/perf_probe.py:247` `fc = App(qapp=app_qt)` in `time.perf_counter()`), records the result via the existing `record()`/`RESULTS` machinery (`tests/perf_probe.py:56-59`), prints it in the summary table, then exits without running the interactive probes. Default (flag unset) preserves today's behavior exactly. |
| `-X importtime` recipe | docs / harness comment | Document `python -X importtime flatcam.py 2> importtime.log` and a small post-processor that sorts the `cumulative` column to rank the heaviest module imports. This is how hypothesis (1)/(2) (matplotlib, descartes, vispy, preprocessor source-loading) get quantified and ranked. |
| `cProfile` of `App.__init__` recipe | docs / harness comment | Document profiling the constructor: `python -m cProfile -o startup.prof flatcam.py` with an early auto-quit (reuse the `QTimer.singleShot` + `os._exit(0)` pattern already in `tests/perf_probe.py:268,265`), then rank with `pstats` (`sort cumtime`) to attribute time to `on_plotcanvas_setup`, `load_preprocessors`, `register_all_commands`, and the plugin-construction block. |

**Output of the harness phase:** a **ranked breakdown** (import-time + init-time)
that orders the candidates below by actual cost. Only candidates that show
meaningful, repeatable cost proceed to implementation.

### B. Candidate optimizations (HYPOTHESES — implement only what measurement justifies)

| # | Hypothesis | Change (if confirmed) | Code anchor |
|---|---|---|---|
| H1 | matplotlib + QtAgg backend + descartes are imported at startup but unused in the default VisPy mode | Move `from appGUI.PlotCanvasLegacy import PlotCanvasLegacy` out of module top (`appMain.py:62`) into the legacy branch of `on_plotcanvas_setup()` (`appMain.py:7362-7363`), mirroring the **already-existing** lazy import of `ShapeCollectionLegacy` at `appMain.py:979`. | `appMain.py:62`, `:7362-7363`, `PlotCanvasLegacy.py:15,27-39` |
| H2 | The VisPy `PlotCanvas` is imported even when the user runs in 2D mode | Move `from appGUI.PlotCanvas import PlotCanvas` (`appMain.py:61`) into the 3D branch of `on_plotcanvas_setup()` (`appMain.py:7349-7350`). (Lower priority: VisPy is also pulled by `VisPyVisuals`/`VisPyPatches` regardless, so the marginal win may be small — measure.) | `appMain.py:61`, `:7349-7350` |
| H3 | `PlotCanvas3d` is only ever used by the "3D Area" tab | Move `from appGUI.PlotCanvas3d import PlotCanvas3d` (`appMain.py:63`) into `on_3d_area()` immediately before `appMain.py:5295`. Pure deferred import; the 3D Area feature still works on first click. | `appMain.py:63`, `:5295` |
| H4 | The `pkgutil.walk_packages` pass re-imports Tcl modules already imported by the explicit list | Remove the redundant `walk_packages` loop (`tclCommands/__init__.py:88-90`) since all command modules are already explicitly imported (`:7-79`); `register_all_commands()` reads `sys.modules` (`:110-111`) and does not depend on the walk. Confirm no module outside the explicit list exists, then drop the loop. | `tclCommands/__init__.py:88-90` |
| H5 | `load_preprocessors` globs and may double-load the same directory | If `app.data_path/preprocessors` and `./preprocessors` resolve to the same files, avoid loading twice; the metaclass already warns on override (`appPreProcessor.py:26-27`), indicating real double-registration today. De-dup the search paths. **Keep all preprocessors eager.** | `appPreProcessor.py:148-160` |
| H6 | A redundant plot/redraw or hidden-UI build runs during startup | Only if the cProfile reveals one. (Current reading shows the per-object `plot_all()` at `appMain.py:5795` is in `on_toolbar_replot`, a user action — **not** an unconditional startup pass — so this is speculative pending the profile.) | `appMain.py:6926` (`plot_all`), `:5795` |

Priority order is set by the ranked breakdown from section A. **H1 is the leading
hypothesis** (matplotlib import is the most likely large, cleanly-removable cost in
the default configuration) and has a direct in-repo precedent (the lazy
`ShapeCollectionLegacy` import at `appMain.py:979`).

## Data flow

**Measurement loop (per candidate):**

1. Run baseline: `FLATCAM_PERF_STARTUP=1 python tests/perf_probe.py` (records
   `App.__init__` ms) **and** `python -X importtime flatcam.py` (ranked import
   costs) **and** the cProfile recipe (ranked `cumtime`). Capture numbers.
2. Apply one candidate change (e.g. H1: relocate the `PlotCanvasLegacy` import).
3. Re-run the same three measurements.
4. Keep the change only if the startup delta is positive and repeatable across a
   few runs; otherwise revert. Record before/after in `CHANGELOG.md`
   (per repo convention).

**Runtime flow after a deferred-import change (must be identical to today):**

- Default launch (`global_graphic_engine != '2D'`): `on_plotcanvas_setup()` takes
  the 3D branch (`appMain.py:7348-7361`) → `PlotCanvas(self)`. With H1 applied,
  matplotlib/descartes are never imported. Canvas, shapes
  (`appMain.py:955-977`), and all downstream behavior unchanged.
- Legacy launch (`global_graphic_engine == '2D'`, or Ctrl-modifier at
  `appMain.py:7345-7346`): the legacy branch (`appMain.py:7362-7365`) runs the
  newly-relocated `from appGUI.PlotCanvasLegacy import PlotCanvasLegacy` **before**
  `PlotCanvasLegacy(self)` is constructed — so matplotlib loads exactly when first
  needed, with no observable difference except that this path now pays the import
  cost it previously paid at startup.
- "3D Area" tab (H3): `on_3d_area()` imports `PlotCanvas3d` on first invocation,
  before `appMain.py:5295`. The guard at `appMain.py:5278-5281` (legacy mode
  rejects 3D) is untouched.

## Error handling

- **Deferred-import failure must fail exactly where the eager import would have
  failed today.** For H1, if matplotlib is missing, `PlotCanvasLegacy.py:35-36`
  already sets `MATPLOTLIB_AVAILABLE = False`; the relocated import must preserve
  the existing `on_plotcanvas_setup()` legacy error path
  (`appMain.py:7364-7365` returns `'fail'`, handled at `appMain.py:939-945`). No
  new failure modes.
- **H3:** keep `PlotCanvas3d` construction inside the existing try/except in
  `on_3d_area()` (`appMain.py:5294-5303`); a relocated import that raises
  `ImportError` is caught the same way (returns `'fail'`, informs the user) rather
  than crashing startup.
- **H4/H5 (redundant-work removal):** must be behavior-preserving. After removing
  the `walk_packages` pass, verify the registered command set
  (`register_all_commands`, `tclCommands/__init__.py:93-128`) is identical
  (same aliases) to the baseline. After de-duping preprocessor paths, verify
  `self.preprocessors` (`appMain.py:757`) contains the same keys.
- The harness wraps each timed step in try/except (existing pattern,
  `tests/perf_probe.py:56-59,124-130`); a failed measurement prints FAIL and does
  not abort the run. The startup-mode flag must default OFF so the harness's normal
  interactive behavior is unchanged when the flag is absent.

## Testing strategy

(Repo has no automated suite — verification is manual + harness-driven.)

1. **Baseline capture:** record `App.__init__` ms (`FLATCAM_PERF_STARTUP=1
   tests/perf_probe.py`), the `-X importtime` ranked log, and the cProfile ranked
   `cumtime` — all on the unmodified tree. This is the ranked breakdown deliverable.
2. **Per-change delta:** re-run the same three measurements after each candidate;
   require a positive, repeatable startup delta to keep the change.
3. **Behavior parity — default (VisPy) mode:** launch `python flatcam.py`, confirm
   the window, canvas, all toolbar/menu tools, and the Tcl shell appear and work as
   before; confirm no first-use delay on any tool.
4. **Behavior parity — legacy (2D) mode:** set `global_graphic_engine='2D'` (and
   test the Ctrl-modifier path), confirm the matplotlib canvas builds and plots,
   and that matplotlib now imports lazily without error (H1).
5. **3D Area tab (H3):** open the "3D Area" tab and confirm it builds on first
   click; confirm legacy mode still rejects it via `appMain.py:5278-5281`.
6. **Tcl parity (H4):** in the shell, run `help` / list commands; confirm the full
   command set is present and a representative command (e.g. `isolate`, `cncjob`)
   executes — identical to baseline.
7. **Preprocessor parity (H5):** confirm every preprocessor still appears in the
   relevant combo boxes and that no `Preprocessor ... has been overriden`
   warnings (`appPreProcessor.py:27`) regress (they should ideally disappear).
8. **Regression guard:** re-run the existing interactive probes
   (`tests/perf_probe.py` with the flag unset) to confirm no interactive-path
   regression from the import relocations.
9. Record before/after numbers and the accepted changes in `CHANGELOG.md`.

## Out of scope / non-goals

- **No lazy construction of the ~35 plugins** (`appMain.py:1662-1832`,
  `appPlugins/__init__.py:1-53`). They stay eagerly built; no first-use delay.
- **No lazy loading of preprocessors or Tcl commands** beyond removing strictly
  redundant *duplicate* work (H4/H5). The full sets remain available at startup.
- **No deferral of either graphics backend's first-use availability** — only the
  *import* of the backend that isn't selected this session is deferred; switching
  engines (`appMain.py:7340-7346`) continues to work.
- **No interactive-performance work** — that was commit `9b2a02f7`; this spec does
  not touch `info()`, mouse-move, HUD, `plot2()`, or selection/hover buffering.
- **No splash-screen / perceived-startup tricks**, no threading of `App.__init__`,
  no reordering that changes when the window becomes visible — only honest
  import/redundant-work reduction.
- **No new settings/preferences keys** and no changes to `defaults.py`
  `factory_defaults`.
- **No packaging/PyInstaller changes** (`build_windows.ps1`); import deferral must
  remain compatible with the frozen build but optimizing the freeze is out of scope.
- **No optimization committed on intuition** — anything not backed by a ranked
  measurement and a confirmed before/after delta is explicitly excluded.
