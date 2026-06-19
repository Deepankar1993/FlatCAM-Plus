# Auto-Save & Crash Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reliable, non-intrusive auto-save with crash recovery to FlatCAM Evo — work survives an unclean shutdown even if the project was never manually saved, and the user is prompted to restore on the next launch.

**Architecture:** A new small `AppAutoSave` class (`appHandlers/appAutoSave.py`) owns a QTimer, the recovery-folder path, snapshot writes (delegated to the existing thread-safe `save_project()` on a worker thread), version rotation, and the session-marker lifecycle. The file-system logic is exposed as **pure module-level functions** so it is testable against a temp directory with no Qt. `appMain.py` instantiates the class, replaces the old `save_project_auto*` bodies, creates/clears the session marker around the app lifecycle, and shows a restore dialog on launch after an unclean exit.

**Tech Stack:** Python 3.11, PyQt6 (`QtCore.QTimer`, `pyqtSignal`), Shapely-based project serialization (reused, not modified). No new dependencies.

## Global Constraints

- Python >= 3.6 (3.11 verified); Shapely >= 2.0. No new third-party dependencies.
- Never touch the GUI from a worker thread — GUI updates go through Qt signals
  (`self.app.inform.emit(...)`), which are thread-safe to emit.
- Reuse the existing thread-safe serializer `appIO.save_project(filename, quit_action, silent, from_tcl)`; do not write a second serializer.
- User-facing strings wrapped in `_('...')` (gettext).
- Recovery data lives under `self.app.data_path` (already resolved in `appMain.py`
  to `%APPDATA%\FlatCAM` / `~/.FlatCAM` / portable `config/`).
- No automated test suite / pytest. Logic tests are standalone scripts under
  `tests/` run with the build venv: `.venv-build\Scripts\python.exe tests\<name>.py`,
  printing a `PASS=n FAIL=n` summary and exiting non-zero on failure.
- Use existing custom widgets (`FCCheckBox`, `FCSpinner`, `FCLabel`) in preferences UI.
- Settings keys: reuse `global_autosave` (bool) and `global_autosave_timeout` (int ms,
  default becomes `30000`); add `global_autosave_keep` (int, default `10`).

---

## File Structure

- **Create** `appHandlers/appAutoSave.py` — pure FS-helper functions + `AppAutoSave` class.
- **Create** `tests/autosave_test.py` — standalone logic test for the FS helpers (temp dir, no Qt).
- **Modify** `defaults.py` — change `global_autosave_timeout` default to `30000`; add `global_autosave_keep`.
- **Modify** `appGUI/preferences/general/GeneralAppPrefGroupUI.py` — add "Keep N backups" spinner + tooltips.
- **Modify** `appMain.py` — instantiate `AppAutoSave`; rewire `save_project_auto()` / `save_project_auto_update()`; create session marker at startup; check-for-recovery dialog on launch; clear recovery on clean exit.

**Dependency order:** Task 1 (class) and Task 2 (settings) and Task 3 (prefs UI) are
independent and parallelizable. Task 4 (wiring) depends on Tasks 1 & 2. Task 5
(verification) depends on all.

---

### Task 1: `AppAutoSave` class + pure FS helpers

**Files:**
- Create: `appHandlers/appAutoSave.py`
- Test: `tests/autosave_test.py`

**Interfaces:**
- Consumes: nothing from other tasks. At runtime consumes `app.data_path` (str),
  `app.options` (dict-like), `app.project_filename` (str|None),
  `app.block_autosave`/`app.should_we_save`/`app.save_in_progress` (bool),
  `app.worker_task` (pyqtSignal(dict)), `app.inform` (pyqtSignal),
  `app.f_handlers.save_project(filename, quit_action=False, silent=False)`,
  `app.log` (logger).
- Produces (used by Task 4):
  - Module functions: `recovery_dir(data_path) -> str`,
    `ensure_recovery_dir(data_path) -> str`,
    `snapshot_path(data_path, timestamp_str) -> str`,
    `list_snapshots(data_path) -> list[str]`,
    `newest_snapshot(data_path) -> str|None`,
    `rotate(data_path, keep:int) -> None`,
    `write_marker(data_path, snapshot:str|None, project_filename:str|None) -> None`,
    `read_marker(data_path) -> dict|None`,
    `marker_exists(data_path) -> bool`,
    `clear_recovery(data_path) -> None`.
  - Class `AppAutoSave(QtCore.QObject)` with methods
    `start()`, `stop()`, `update_interval()`, `create_session_marker()`,
    `check_for_recovery() -> dict|None`, `do_snapshot()`, `mark_clean_exit()`.

- [ ] **Step 1: Write the failing test** — create `tests/autosave_test.py`:

```python
"""Standalone logic test for appHandlers/appAutoSave FS helpers (no Qt)."""
import os, sys, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from appHandlers import appAutoSave as a

PASS = 0
FAIL = 0

def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("FAIL:", msg)

def run():
    d = tempfile.mkdtemp(prefix="fc_autosave_")
    try:
        # recovery_dir / ensure
        rec = a.ensure_recovery_dir(d)
        check(rec == os.path.join(d, "recovery"), "recovery_dir path")
        check(os.path.isdir(rec), "ensure_recovery_dir creates folder")

        # snapshot_path
        sp = a.snapshot_path(d, "20260619_120000")
        check(sp.endswith("autosave_20260619_120000.FlatPrj"), "snapshot_path name")

        # list/newest with 3 snapshots
        for ts in ("20260619_120000", "20260619_120030", "20260619_120100"):
            open(a.snapshot_path(d, ts), "w").close()
        snaps = a.list_snapshots(d)
        check(len(snaps) == 3, "list_snapshots count")
        check(a.newest_snapshot(d).endswith("120100.FlatPrj"), "newest_snapshot")

        # rotate keep=2 removes the oldest
        a.rotate(d, keep=2)
        snaps = a.list_snapshots(d)
        check(len(snaps) == 2, "rotate keeps 2")
        check(all("120000.FlatPrj" not in s for s in snaps), "rotate dropped oldest")

        # marker write/read/exists
        check(a.marker_exists(d) is False, "no marker initially")
        a.write_marker(d, a.newest_snapshot(d), "C:/proj.FlatPrj")
        check(a.marker_exists(d) is True, "marker exists after write")
        m = a.read_marker(d)
        check(m["snapshot"].endswith("120100.FlatPrj"), "marker snapshot")
        check(m["project_filename"] == "C:/proj.FlatPrj", "marker project_filename")

        # write_marker with None snapshot (startup marker)
        a.write_marker(d, None, None)
        m = a.read_marker(d)
        check(m["snapshot"] is None, "startup marker snapshot None")

        # clear_recovery removes snapshots + marker
        a.clear_recovery(d)
        check(a.list_snapshots(d) == [], "clear_recovery removes snapshots")
        check(a.marker_exists(d) is False, "clear_recovery removes marker")

        # read_marker on missing returns None
        check(a.read_marker(d) is None, "read_marker missing -> None")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("AUTOSAVE TEST: PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)

if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv-build\Scripts\python.exe tests\autosave_test.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'appHandlers.appAutoSave'`
(or `AttributeError` once the file exists but functions are missing).

- [ ] **Step 3: Write the FS helpers + class** — create `appHandlers/appAutoSave.py`:

```python
# ##########################################################
# FlatCAM Evo: Auto-Save & Crash Recovery
# ##########################################################

import os
import glob
import json
import traceback
from datetime import datetime

from PyQt6 import QtCore

import gettext
import appTranslation as fcTranslate
import builtins

fcTranslate.apply_language('strings')
if '_' not in builtins.__dict__:
    _ = gettext.gettext

AUTOSAVE_GLOB = "autosave_*.FlatPrj"
MARKER_NAME = "session.lock"


def recovery_dir(data_path):
    return os.path.join(data_path, "recovery")


def ensure_recovery_dir(data_path):
    d = recovery_dir(data_path)
    os.makedirs(d, exist_ok=True)
    return d


def snapshot_path(data_path, timestamp_str):
    return os.path.join(recovery_dir(data_path), "autosave_%s.FlatPrj" % timestamp_str)


def list_snapshots(data_path):
    # timestamp embedded in the name => lexicographic sort == chronological order
    return sorted(glob.glob(os.path.join(recovery_dir(data_path), AUTOSAVE_GLOB)))


def newest_snapshot(data_path):
    snaps = list_snapshots(data_path)
    return snaps[-1] if snaps else None


def rotate(data_path, keep):
    snaps = list_snapshots(data_path)
    doomed = snaps if keep <= 0 else snaps[:-keep]
    for old in doomed:
        try:
            os.remove(old)
        except OSError:
            pass


def _marker_path(data_path):
    return os.path.join(recovery_dir(data_path), MARKER_NAME)


def write_marker(data_path, snapshot, project_filename):
    ensure_recovery_dir(data_path)
    with open(_marker_path(data_path), "w") as f:
        json.dump({"snapshot": snapshot, "project_filename": project_filename}, f)


def read_marker(data_path):
    p = _marker_path(data_path)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def marker_exists(data_path):
    return os.path.exists(_marker_path(data_path))


def clear_recovery(data_path):
    for s in list_snapshots(data_path):
        try:
            os.remove(s)
        except OSError:
            pass
    p = _marker_path(data_path)
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass


class AppAutoSave(QtCore.QObject):
    """
    Owns the auto-save QTimer, recovery snapshots, version rotation and the
    session-marker lifecycle used for crash recovery.
    """

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.do_snapshot)

    @property
    def data_path(self):
        return self.app.data_path

    # ----- timer control -----
    def start(self):
        self.update_interval()

    def stop(self):
        if self.timer.isActive():
            self.timer.stop()

    def update_interval(self):
        if self.timer.isActive():
            self.timer.stop()
        if self.app.options.get('global_autosave') is True:
            self.timer.setInterval(int(self.app.options['global_autosave_timeout']))
            self.timer.start()

    # ----- session marker -----
    def create_session_marker(self):
        try:
            ensure_recovery_dir(self.data_path)
            write_marker(self.data_path, None, self.app.project_filename)
        except OSError:
            self.app.log.error("AppAutoSave.create_session_marker() failed:\n%s" % traceback.format_exc())

    def check_for_recovery(self):
        """Return the marker dict from a *previous* unclean session, else None."""
        return read_marker(self.data_path)

    def mark_clean_exit(self):
        try:
            clear_recovery(self.data_path)
        except OSError:
            self.app.log.error("AppAutoSave.mark_clean_exit() failed:\n%s" % traceback.format_exc())

    # ----- snapshot -----
    def do_snapshot(self):
        if not (self.app.block_autosave is False
                and self.app.should_we_save is True
                and self.app.save_in_progress is False):
            return
        try:
            ensure_recovery_dir(self.data_path)
        except OSError:
            self.app.log.error("AppAutoSave: cannot create recovery dir; auto-save disabled this tick.")
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = snapshot_path(self.data_path, timestamp)
        self.app.worker_task.emit({'fcn': self._snapshot_worker, 'params': [path]})

    def _snapshot_worker(self, path):
        try:
            self.app.f_handlers.save_project(path, silent=True)
            write_marker(self.data_path, path, self.app.project_filename)
            keep = int(self.app.options.get('global_autosave_keep', 10))
            rotate(self.data_path, keep)
            # inform is a Qt signal => safe to emit from a worker thread
            self.app.inform.emit('[success] %s' % _("Auto-saved"))
        except Exception:
            self.app.log.error("AppAutoSave._snapshot_worker() failed:\n%s" % traceback.format_exc())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv-build\Scripts\python.exe tests\autosave_test.py`
Expected: `AUTOSAVE TEST: PASS=15 FAIL=0`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add appHandlers/appAutoSave.py tests/autosave_test.py
git commit -m "feat(autosave): AppAutoSave class + recovery FS helpers with logic tests"
```

---

### Task 2: Settings defaults

**Files:**
- Modify: `defaults.py` (the `factory_defaults` dict — `global_autosave_timeout` ~line 100)

**Interfaces:**
- Consumes: nothing.
- Produces: `global_autosave_timeout` default `30000`; new key `global_autosave_keep` default `10` (read by Task 1 `_snapshot_worker` and Task 3 prefs UI).

- [ ] **Step 1: Change the timeout default and add the keep key**

In `defaults.py`, locate:

```python
    "global_autosave":              False,
    "global_autosave_timeout":      300000,
```

Replace with:

```python
    "global_autosave":              False,
    "global_autosave_timeout":      30000,
    "global_autosave_keep":         10,
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `.venv-build\Scripts\python.exe -c "import defaults; print(defaults.factory_defaults['global_autosave_timeout'], defaults.factory_defaults['global_autosave_keep'])"`
Expected: `30000 10`

- [ ] **Step 3: Commit**

```bash
git add defaults.py
git commit -m "feat(autosave): default interval 30s, add global_autosave_keep=10"
```

---

### Task 3: Preferences UI — "Keep N backups" spinner

**Files:**
- Modify: `appGUI/preferences/general/GeneralAppPrefGroupUI.py` (the auto-save block, ~lines 319–342)

**Interfaces:**
- Consumes: `global_autosave_keep` key name from Task 2.
- Produces: a widget attribute `self.autosave_keep_entry` (an `FCSpinner`) bound to
  `global_autosave_keep` so the existing `PreferencesUIManager` auto-binds it. The
  manager binds widgets to options by the attribute-name → option-key convention used
  by the surrounding widgets (`autosave_cb` ↔ `global_autosave`,
  `autosave_entry` ↔ `global_autosave_timeout`); follow that exact convention so the
  new spinner is auto-bound the same way (verify against neighbors before finalizing).

- [ ] **Step 1: Read the existing auto-save block** to copy the precise pattern

Read `appGUI/preferences/general/GeneralAppPrefGroupUI.py` around lines 315–345 to see
how `self.autosave_cb`, `self.autosave_label`, `self.autosave_entry` are created, added
to the grid, and tooltipped, and how the option key is wired in `PreferencesUIManager`.

- [ ] **Step 2: Add the "Keep backups" spinner** directly after the interval spinner
rows. Match the surrounding grid-add style (the real row/grid variable names come from
Step 1 — use them verbatim):

```python
        # Auto Save - number of backups to keep
        self.autosave_keep_label = FCLabel('%s:' % _('Keep backups'))
        self.autosave_keep_label.setToolTip(
            _("How many auto-save recovery files to keep.\n"
              "Older ones are deleted automatically.")
        )
        self.autosave_keep_entry = FCSpinner()
        self.autosave_keep_entry.set_range(1, 999)
        self.autosave_keep_entry.setWrapping(True)

        # add to the same grid used by autosave_entry, on the next free row:
        param_grid.addWidget(self.autosave_keep_label, <next_row>, 0)
        param_grid.addWidget(self.autosave_keep_entry, <next_row>, 1)
```

- [ ] **Step 3: Refresh the existing tooltips** for clarity. Update the interval
spinner tooltip to read (replace the existing `setToolTip` text on `autosave_entry`):

```python
        self.autosave_entry.setToolTip(
            _("Time interval for autosaving, in milliseconds.\n"
              "Auto-save writes a crash-recovery snapshot to the\n"
              "recovery folder; it does not overwrite your project file.")
        )
```

- [ ] **Step 4: Register the option binding** if the surrounding widgets are listed
explicitly in `PreferencesUIManager` (some builds enumerate the mapping). If Step 1
shows an explicit `(widget, 'global_autosave_timeout')`-style list, add the analogous
entry `(self.autosave_keep_entry, 'global_autosave_keep')`. If binding is purely by
convention, no change is needed.

- [ ] **Step 5: Verify the preferences module imports**

Run: `.venv-build\Scripts\python.exe -c "import appGUI.preferences.general.GeneralAppPrefGroupUI as m; print('ok')"`
Expected: `ok` (no syntax/import error).

- [ ] **Step 6: Commit**

```bash
git add appGUI/preferences/general/GeneralAppPrefGroupUI.py
git commit -m "feat(autosave): preferences spinner to keep N recovery backups"
```

---

### Task 4: Wire `AppAutoSave` into the app lifecycle

**Files:**
- Modify: `appMain.py`
  - import + instantiate near where `autosave_timer` is currently created (~line 853–856)
  - replace `save_project_auto()` body (~line 7848)
  - replace `save_project_auto_update()` body (~line 7860)
  - add startup recovery check + session marker (end of `App.__init__`, after the GUI/collection are ready)
  - clear recovery on clean exit in `close_application()` (~line 3818 area)

**Interfaces:**
- Consumes from Task 1: `from appHandlers.appAutoSave import AppAutoSave` and its methods
  `start/stop/update_interval/create_session_marker/check_for_recovery/do_snapshot/mark_clean_exit`,
  plus module fn `newest_snapshot`.
- Consumes from Task 2: `global_autosave_keep`.
- Produces: `self.autosave` instance on the `App`.

- [ ] **Step 1: Import and instantiate.** At the top of `appMain.py` with the other
`appHandlers` imports, add:

```python
from appHandlers.appAutoSave import AppAutoSave, newest_snapshot
```

Then replace the existing timer creation block (currently around lines 853–856):

```python
        self.block_autosave = False
        self.autosave_timer = QtCore.QTimer(self)
        self.save_project_auto_update()
        self.autosave_timer.timeout.connect(self.save_project_auto)
```

with:

```python
        self.block_autosave = False
        self.autosave = AppAutoSave(self)
        self.autosave.start()
```

- [ ] **Step 2: Replace `save_project_auto()`** (currently ~line 7848) so external
callers (preferences `Apply`, etc.) keep working but delegate to the new class:

```python
    def save_project_auto(self):
        """Periodic auto-save tick — delegated to AppAutoSave."""
        self.autosave.do_snapshot()
```

- [ ] **Step 3: Replace `save_project_auto_update()`** (currently ~line 7860):

```python
    def save_project_auto_update(self):
        """Re-read the auto-save interval / enabled flag and restart the timer."""
        self.log.debug("App.save_project_auto_update() --> updated the interval timeout.")
        self.autosave.update_interval()
```

- [ ] **Step 4: Startup recovery check + session marker.** Find the end of
`App.__init__` (after the object collection, GUI, and any command-line project load are
set up — search for the last lines of `__init__`, e.g. where `self.ui.show()` or the
final signals are connected). Add, guarded by the setting:

```python
        # ----- Auto-save crash recovery -----
        if self.options.get('global_autosave') is True:
            self.check_autosave_recovery()
        self.autosave.create_session_marker()
```

Then add the method (place it next to `save_project_auto`):

```python
    def check_autosave_recovery(self):
        """
        On launch, if a session marker from a previous *unclean* exit is found,
        offer to restore the newest recovery snapshot.
        """
        marker = self.autosave.check_for_recovery()
        if not marker:
            return
        snap = marker.get("snapshot") or newest_snapshot(self.data_path)
        if not snap or not os.path.exists(snap):
            # stale marker, nothing usable to restore
            self.autosave.mark_clean_exit()
            return

        msgbox = QtWidgets.QMessageBox()
        msgbox.setWindowTitle(_("Restore Auto-Saved Project"))
        msgbox.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        msgbox.setText(_("FlatCAM did not shut down cleanly."))
        msgbox.setInformativeText(_("Restore your last auto-saved project?"))
        btn_restore = msgbox.addButton(_("Restore"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        btn_discard = msgbox.addButton(_("Discard"), QtWidgets.QMessageBox.ButtonRole.DestructiveRole)
        msgbox.addButton(_("Keep files"), QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msgbox.setDefaultButton(btn_restore)
        msgbox.exec()
        clicked = msgbox.clickedButton()

        if clicked == btn_restore:
            # open the snapshot through the normal project-open path
            self.f_handlers.open_project(snap)
            self.inform.emit('[success] %s' % _("Auto-saved project restored."))
        elif clicked == btn_discard:
            self.autosave.mark_clean_exit()
        else:
            # Keep files: drop only the stale marker so we don't re-prompt next launch
            from appHandlers.appAutoSave import clear_recovery, write_marker  # local import to avoid cycle noise
            try:
                os.remove(os.path.join(self.data_path, "recovery", "session.lock"))
            except OSError:
                pass
```

> Implementer note: confirm the project-open entry point name. The handler is on
> `self.f_handlers`; in this codebase project open is `open_project(filename)` (verify by
> grep `def open_project` in `appHandlers/appIO.py`; if the signature differs, match it —
> e.g. some builds use `open_project(filename, run_from_arg=...)`). `QtWidgets` is already
> imported in `appMain.py`; verify and add to the import if not.

- [ ] **Step 5: Clear recovery on clean exit.** In `close_application()` (the normal quit
path, ~line 3818, where `save_in_progress` is checked), after the app has decided it is
genuinely quitting (and any "save changes?" handling is done), add:

```python
        # auto-save: a clean exit means there is nothing to recover
        try:
            self.autosave.stop()
            self.autosave.mark_clean_exit()
        except Exception:
            pass
```

> Implementer note: place this on the actual quit branch, not before a user might cancel
> the quit. If `close_application()` can early-return when the user cancels, the cleanup
> must be after that point so cancelling a quit does NOT wipe recovery files.

- [ ] **Step 6: Smoke-test that the app constructs and the timer is wired.** Create a
throwaway harness (do not commit it) modeled on `tests/perf_probe.py` that instantiates
`App`, asserts `app.autosave.timer is not None`, calls `app.autosave.do_snapshot()` once
after setting `app.should_we_save = True`, waits briefly for the worker, and asserts a
file matching `recovery/autosave_*.FlatPrj` exists under `app.data_path`, then
`os._exit(0)`. Run:

`.venv-build\Scripts\python.exe tests\_autosave_smoke.py`
Expected: prints `SMOKE: PASS` and a snapshot path; exit 0. Delete the harness after.

- [ ] **Step 7: Commit**

```bash
git add appMain.py
git commit -m "feat(autosave): wire AppAutoSave, startup recovery prompt, clean-exit cleanup"
```

---

### Task 5: End-to-end verification (manual) + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md` (add a dated entry)

**Interfaces:**
- Consumes: the fully wired feature from Tasks 1–4.
- Produces: nothing code-facing; a documented, verified feature.

- [ ] **Step 1: Run the logic test** (regression guard):

Run: `.venv-build\Scripts\python.exe tests\autosave_test.py`
Expected: `AUTOSAVE TEST: PASS=15 FAIL=0`.

- [ ] **Step 2: Manual GUI verification.** Launch `python flatcam.py`. In
Edit → Preferences → General, enable "Enable Auto Save", set interval `30000`, set
"Keep backups" `10`, Apply. Then:
  1. Create/modify an object; within 30 s confirm an `autosave_*.FlatPrj` appears in
     the recovery folder and a transient `Auto-saved` shows in the status bar.
     **Crucially: confirm NO "Save As" dialog appears for a never-saved project.**
  2. Let it run a few minutes; confirm at most 10 snapshots remain (rotation works).
  3. Kill the process (Task Manager / `taskkill`) to simulate a crash. Relaunch;
     confirm the **restore dialog** appears; click Restore; confirm the project loads.
  4. Quit cleanly (File → Exit); relaunch; confirm **no** prompt and the recovery
     folder is cleared.
  5. Disable auto-save, Apply; confirm the timer stops (no new snapshots).

- [ ] **Step 3: Record results** of Step 2 (pass/fail per sub-step) in the PR / handoff.

- [ ] **Step 4: Add a CHANGELOG entry.** At the top of `CHANGELOG.md` add a dated
section:

```markdown
## [Unreleased] - 2026-06-19

### Added
- Auto-save crash recovery: when enabled, the project is snapshotted to a recovery
  folder every 30 s (configurable), keeping the last 10 versions. After an unclean
  shutdown, FlatCAM offers to restore the last auto-saved project on next launch.
  Works even for never-saved projects (no more Save As dialog during auto-save).
```

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(autosave): changelog entry for crash-recovery auto-save"
```

---

## Self-Review

**Spec coverage:**
- Recovery folder layout / `session.lock` / snapshots → Task 1 (helpers) + Task 4 (marker lifecycle). ✓
- 30 s interval default → Task 2. ✓
- Keep last 10 + rotation → Task 1 `rotate()` + Task 2 key + Task 3 UI. ✓
- Never-saved-project gap (no Save As) → Task 1 `do_snapshot` writes to recovery path directly; Task 5 step 2.1 verifies. ✓
- Silent worker save + `Auto-saved ✓` indicator → Task 1 `_snapshot_worker` (uses `inform`). ✓
- Restore-on-launch dialog (Restore/Discard/Keep) → Task 4 `check_autosave_recovery`. ✓
- Clean-exit clears recovery → Task 4 Step 5. ✓
- Error handling / logging, no GUI from worker → Task 1 (try/except + `inform` signal). ✓
- Disabled = no timer/prompt → Task 1 `update_interval`, Task 4 startup guard. ✓

**Placeholder scan:** Concrete code in every code step. Two deliberate
`<next_row>` / `<name>` placeholders in Task 3 are flagged as "use the real grid var
from Step 1" because exact grid variable names must be read from the file first; Task 3
Step 1 forces that read. Task 4 includes implementer-verify notes for the exact
project-open entry point and quit branch — these are codebase-confirmation points, not
unspecified logic.

**Type consistency:** `do_snapshot`, `_snapshot_worker`, `rotate(data_path, keep)`,
`newest_snapshot`, `write_marker(data_path, snapshot, project_filename)`,
`read_marker`, `clear_recovery`, `mark_clean_exit`, `create_session_marker`,
`check_for_recovery`, `update_interval` — names identical across Tasks 1 and 4. Option
keys `global_autosave` / `global_autosave_timeout` / `global_autosave_keep` consistent
across Tasks 1–4. ✓
