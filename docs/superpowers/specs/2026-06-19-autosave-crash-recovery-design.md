# Auto-Save & Crash Recovery — Design Spec

**Date:** 2026-06-19
**Component:** FlatCAM Evo (PyQt6 desktop CAM app)
**Status:** Approved for implementation planning

## Goal

Provide reliable, non-intrusive auto-save with crash recovery. Work must survive
an unclean shutdown (crash / power loss) even if the user never manually saved
the project. On the next launch after an unclean exit, the user is prompted to
restore their last auto-saved state.

## Why the current implementation is insufficient

Auto-save plumbing already exists but is effectively broken for the crash case:

- `appMain.save_project_auto()` calls `appIO.on_file_save_project()`, which pops a
  modal **"Save As" dialog** whenever `project_filename is None` (a never-saved
  project). Auto-save therefore does nothing useful — and can interrupt the user —
  until they manually save once.
- There is no separate recovery target, no versioned backups, and no
  unclean-shutdown detection / restore-on-launch flow.

Relevant existing code:

- `defaults.py`: `global_autosave` (bool, default `False`), `global_autosave_timeout`
  (int ms, default `300000`).
- `appGUI/preferences/general/GeneralAppPrefGroupUI.py` (~lines 319–342):
  `autosave_cb` checkbox + `autosave_entry` interval spinner.
- `appMain.py`: `autosave_timer` (QTimer) → `save_project_auto()`; interval set by
  `save_project_auto_update()`; gated by `block_autosave` / `should_we_save` /
  `save_in_progress`.
- `appHandlers/appIO.py`: `save_project(filename, quit_action, silent, from_tcl)`
  (the thread-safe serializer), `on_file_save_project()`, `on_file_save_project_as()`.
- Save runs on a worker thread via `self.worker_task.emit({'fcn': ..., 'params': ...})`.
- User notifications via `self.inform.emit('[success] ...')`.

## Decisions (locked)

- **Scope:** full crash-recovery system (versioned backups + restore-on-launch prompt).
- **Interval:** 30 seconds (`global_autosave_timeout` default → `30000`).
- **Retention:** keep the last **10** snapshots; rotate out older ones.
- **Restore UX:** auto-prompt dialog on next launch after an unclean shutdown
  (Restore / Discard / Keep files).
- **Indicator:** subtle `Auto-saved ✓` flash in the status bar on each successful
  snapshot (reuses the `inform` signal; not an error/blocking message).

## Recovery folder layout

```
%APPDATA%\FlatCAM\recovery\        (Windows)   |   ~/.FlatCAM/recovery/   (else)
  ├── session.lock                       # exists only while app is running
  └── autosave_YYYYMMDD_HHMMSS.FlatPrj   # up to 10 snapshots, newest wins
```

- The recovery folder lives next to the existing FlatCAM user-settings folder
  (the same base directory already used for `log.txt` / settings; honors the
  `portable=True` config the same way the rest of the app resolves its data dir).
- **Snapshot file** uses the exact same serialized `.FlatPrj` format produced by
  `appIO.save_project()`, so restoring a snapshot is just a normal project open.
- **session.lock** is a small text/JSON marker created at startup and deleted on
  clean exit. It records: the path of the most recent snapshot, and the original
  `project_filename` (if the project was ever manually saved). Its presence at
  launch = the previous session did not exit cleanly.

## Components

| Unit | Location | Responsibility |
|---|---|---|
| `AppAutoSave` (new class) | `appHandlers/appAutoSave.py` (new) | Owns recovery-folder path resolution, snapshot scheduling/write (via worker), retention/rotation, and the session-marker lifecycle. Small, isolated, unit-testable. |
| Settings | `defaults.py` | Reuse `global_autosave` / `global_autosave_timeout` (timeout default → `30000`). Add `global_autosave_keep` (int, default `10`). |
| Preferences UI | `appGUI/preferences/general/GeneralAppPrefGroupUI.py` | Keep existing checkbox + interval spinner; add "Keep N backups" spinner; refresh tooltips. |
| Wiring | `appMain.py` | Replace `save_project_auto()` body to delegate to `AppAutoSave`; create session marker at startup; cleanup on clean exit; check for recovery on launch. |
| Restore prompt | `appMain.py` startup path | If `session.lock` present on launch → modal dialog (Restore / Discard / Keep). |
| Clean-exit hook | `appMain.py` `close_application()` | Delete `session.lock`; clear `autosave_*` snapshots (work was either saved or intentionally abandoned). |

### `AppAutoSave` interface

- `start()` / `stop()` — start/stop the timer based on `global_autosave`.
- `update_interval()` — re-read `global_autosave_timeout`, restart timer
  (replaces the body of `save_project_auto_update`).
- `do_snapshot()` — the timer callback: guard on
  `block_autosave is False and should_we_save is True and save_in_progress is False`;
  build the timestamped recovery path; emit `worker_task` with
  `save_project(recovery_path, silent=True)`; on success update `session.lock`,
  run `rotate()`, and emit the `Auto-saved ✓` indicator.
- `rotate()` — keep newest `global_autosave_keep` `autosave_*.FlatPrj`, delete the rest.
- `create_session_marker()` — write `session.lock` at startup.
- `check_for_recovery()` — at startup, detect a pre-existing `session.lock` (from a
  prior unclean run) and return the snapshot to restore, if any.
- `mark_clean_exit()` — delete `session.lock` and clear snapshots on clean shutdown.

## Data flow & threading

1. Timer fires (GUI thread) → `AppAutoSave.do_snapshot()` checks dirty/in-progress flags.
2. Emits `worker_task` → `appIO.save_project(recovery_path, silent=True)` runs on a
   **worker thread** (reuses the existing thread-safe serializer; no GUI access from
   the worker).
3. On success (signaled back / on return): update `session.lock`, run `rotate()`,
   emit a throttled `Auto-saved ✓` status flash on the GUI thread.
4. Restore-at-launch runs on the **GUI thread** before/around normal project init,
   loading the chosen snapshot through the standard project-open path.

Snapshots never set `project_filename` and never clear the user's manual dirty
state in a way that interferes with their real Save/Save As flow. (`should_we_save`
is intentionally **not** cleared by an auto-snapshot, so the user's own unsaved-changes
tracking against their real project file stays accurate.)

## Error handling

- Any snapshot exception is caught and logged to `log.txt`; it never interrupts the
  user. A failed snapshot leaves the previous good snapshot intact.
- Disk-full / permission errors on the recovery folder are swallowed with a single
  log entry (auto-save silently no-ops rather than nagging).
- If the recovery folder can't be created at startup, auto-save disables itself for
  the session and logs the reason.

## Restore-on-launch UX

On launch, if `session.lock` exists (prior unclean exit) and a valid newest snapshot
is present:

- Dialog: *"FlatCAM didn't shut down cleanly. Restore your last auto-saved project?"*
- **Restore** — open the newest snapshot as the current project; keep the remaining
  snapshots until a clean exit.
- **Discard** — delete the recovery snapshots + marker, start fresh.
- **Keep files** — start fresh but leave snapshots on disk for manual inspection;
  drop the stale marker so the prompt doesn't reappear next launch.

If `global_autosave` is disabled, no prompt and no snapshots are taken.

## Testing (manual — repo has no automated suite)

1. Enable auto-save; make an edit; confirm a snapshot appears in the recovery folder
   within 30 s and the `Auto-saved ✓` flash shows.
2. Verify rotation: force >10 snapshots, confirm only the newest 10 remain.
3. Never-saved project: confirm auto-save writes a recovery snapshot with **no**
   Save As dialog.
4. Simulate crash (kill the process), relaunch, confirm the restore dialog appears
   and Restore loads the work.
5. Clean exit: confirm `session.lock` and snapshots are cleared, and next launch
   shows no prompt.
6. Disable auto-save: confirm timer stops, no snapshots, no prompt.

## Out of scope (YAGNI)

- Cloud / remote backup.
- Per-object incremental export.
- Configurable recovery-folder location (uses the standard user data dir).
- Auto-save of editor sub-states beyond the project serialization already captured.
