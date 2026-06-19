#!/usr/bin/env python3
"""
perf_probe.py -- Performance test harness for FlatCAM Evo.

Instantiates the REAL App (PyQt6) and TIMES the interactive hot paths so we can
measure performance and catch regressions. It does NOT modify any application
source -- it only drives public methods on the running App instance.

Run with the venv that has the deps:

    .venv-build\\Scripts\\python.exe perf_probe.py

The harness:
  1. Locates (or synthesizes) a sample Gerber file.
  2. Times loading that file into the app (open + parse + plot).
  3. Times a burst of N=300 fake mouse-move events over the plot.
  4. Times 50 status-bar info() calls.
  5. Times toggling an object's Plot checkbox.

Each step is wrapped in try/except so one failure does not abort the rest;
every step prints PASS/FAIL with milliseconds. A summary table is printed at
the end. A QTimer.singleShot schedules the work AFTER App construction and a
hard-kill fallback QTimer guarantees the process terminates.

NOTE: Unlike flatcam.py we deliberately do NOT install the custom
sys.excepthook -- we want tracebacks on stderr so failures are visible.
"""

import os
import sys
import time
import tempfile
import traceback

# This harness lives in tests/ but drives the app package at the repo root. Put the
# repo root (parent of this folder) on sys.path so `appMain`/`appGUI` import, and chdir
# to it so the app's CWD-relative resource paths (assets/resources, ...) resolve.
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import QTimer

# VisPyPatches must be applied before the App builds the 3D canvas, exactly as
# flatcam.py does it.
from appGUI import VisPyPatches

# ----------------------------------------------------------------------------
# Results accumulator
# ----------------------------------------------------------------------------
RESULTS = []  # list of dicts: {name, status, ms, detail}


def record(name, status, ms=None, detail=""):
    RESULTS.append({"name": name, "status": status, "ms": ms, "detail": detail})
    ms_str = ("%.3f ms" % ms) if ms is not None else "-"
    print("[%-4s] %-32s %-14s %s" % (status, name, ms_str, detail), flush=True)


# ----------------------------------------------------------------------------
# Step 1: find or synthesize a sample Gerber file
# ----------------------------------------------------------------------------
def find_sample_gerber():
    """Return (path, was_generated). Search the repo, else synthesize."""
    here = ROOT
    candidates = [
        os.path.join(here, "assets", "examples", "files", "test.gbr"),
        os.path.join(here, "assets", "examples", "files", "test_1.gbr"),
        os.path.join(here, "tests_laser", "square.gbr"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c, False

    # Synthesize a Gerber with a few hundred flashes + traces.
    lines = ["%FSLAX26Y26*%", "%MOMM*%", "%ADD10C,0.200000*%", "%ADD11C,0.600000*%"]
    # Traces with D10 (a grid of horizontal segments)
    lines.append("D10*")
    for row in range(20):
        y = (row + 1) * 1000000
        lines.append("X1000000Y%dD02*" % y)
        lines.append("X20000000Y%dD01*" % y)
    # Flashes with D11 (a grid of pads -> a few hundred features)
    lines.append("D11*")
    for row in range(20):
        for col in range(20):
            x = (col + 1) * 1000000
            y = (row + 1) * 1000000
            lines.append("X%dY%dD03*" % (x, y))
    lines.append("M02*")
    gerber_str = "\n".join(lines) + "\n"

    fd, path = tempfile.mkstemp(suffix=".gbr", prefix="perf_probe_")
    with os.fdopen(fd, "w") as f:
        f.write(gerber_str)
    return path, True


# ----------------------------------------------------------------------------
# Fake VisPy-style mouse event for on_mouse_move_over_plot()
# ----------------------------------------------------------------------------
class FakeMouseEvent:
    """Minimal stand-in for a VisPy mouse event.

    on_mouse_move_over_plot reads: event.pos, event.is_dragging, event.button
    """
    def __init__(self, pos, is_dragging=False, button=None):
        self.pos = pos
        self.is_dragging = is_dragging
        self.button = button


# ----------------------------------------------------------------------------
# The timed work, run after the App is up.
# ----------------------------------------------------------------------------
def run_probes(app_qt, fc):
    loaded_obj = None
    sample_path = None
    generated = False

    # ----- Step 1: locate / synthesize sample -----
    try:
        sample_path, generated = find_sample_gerber()
        detail = ("generated" if generated else "found") + ": " + sample_path
        record("locate_sample_gerber", "PASS", None, detail)
    except Exception as e:
        record("locate_sample_gerber", "FAIL", None, repr(e))
        traceback.print_exc()

    # ----- Step 2: time the full open + parse + plot -----
    if sample_path:
        try:
            names_before = set(fc.collection.get_names())
            t0 = time.perf_counter()
            # open_gerber lives on the file handlers object and drives
            # new_object() (parse) + object_created signal (plot).
            fc.f_handlers.open_gerber(sample_path, plot=True)
            # Let queued signals (object_created -> append -> plot) flush.
            app_qt.processEvents()
            t1 = time.perf_counter()

            names_after = set(fc.collection.get_names())
            new_names = names_after - names_before
            if new_names:
                loaded_obj = fc.collection.get_by_name(list(new_names)[0])
                record("open_gerber(open+parse+plot)", "PASS",
                       (t1 - t0) * 1000.0, "object: %s" % list(new_names)[0])
            else:
                record("open_gerber(open+parse+plot)", "FAIL",
                       (t1 - t0) * 1000.0, "no new object appeared in collection")
        except Exception as e:
            record("open_gerber(open+parse+plot)", "FAIL", None, repr(e))
            traceback.print_exc()
    else:
        record("open_gerber(open+parse+plot)", "SKIP", None, "no sample file")

    # ----- Step 3: burst of N=300 fake mouse-move events -----
    N = 300
    try:
        # rel_point1 defaults to (0,0) so the hover/HUD/snap branch executes.
        t0 = time.perf_counter()
        for i in range(N):
            x = 100.0 + (i % 50) * 3.0
            y = 100.0 + (i % 37) * 2.0
            ev = FakeMouseEvent(pos=(x, y), is_dragging=False, button=None)
            fc.on_mouse_move_over_plot(ev)
        t1 = time.perf_counter()
        total_ms = (t1 - t0) * 1000.0
        record("mouse_move x%d (total)" % N, "PASS", total_ms,
               "%.4f ms/call" % (total_ms / N))
    except Exception as e:
        record("mouse_move x%d (total)" % N, "FAIL", None, repr(e))
        traceback.print_exc()

    # ----- Step 4: 50 status-bar info() calls -----
    M = 50
    try:
        t0 = time.perf_counter()
        for i in range(M):
            fc.info('[success] test message %d' % i)
        t1 = time.perf_counter()
        total_ms = (t1 - t0) * 1000.0
        record("info() x%d (total)" % M, "PASS", total_ms,
               "%.4f ms/call" % (total_ms / M))
    except Exception as e:
        record("info() x%d (total)" % M, "FAIL", None, repr(e))
        traceback.print_exc()

    # ----- Step 5: toggle the Plot checkbox -----
    if loaded_obj is not None and hasattr(loaded_obj, "on_plot_cb_click"):
        try:
            # Toggle off then on; time the pair. Guard against muted_ui by
            # reading current value and flipping the form checkbox if present.
            t0 = time.perf_counter()
            try:
                # Flip the UI checkbox if it exists so read_form_item picks it up.
                cb = getattr(loaded_obj.ui, "plot_cb", None)
                if cb is not None:
                    cb.setChecked(not cb.isChecked())
            except Exception:
                pass
            loaded_obj.on_plot_cb_click()
            app_qt.processEvents()
            t1 = time.perf_counter()
            record("on_plot_cb_click (toggle)", "PASS", (t1 - t0) * 1000.0)
        except Exception as e:
            record("on_plot_cb_click (toggle)", "FAIL", None, repr(e))
            traceback.print_exc()
    else:
        record("on_plot_cb_click (toggle)", "SKIP", None, "no loaded object")

    # ----- Cleanup generated temp file -----
    if generated and sample_path:
        try:
            os.remove(sample_path)
        except Exception:
            pass

    # ----- Summary table -----
    print("\n" + "=" * 72, flush=True)
    print("PERF PROBE SUMMARY", flush=True)
    print("=" * 72, flush=True)
    print("%-34s %-8s %-14s" % ("STEP", "STATUS", "TIME"), flush=True)
    print("-" * 72, flush=True)
    for r in RESULTS:
        ms_str = ("%.3f ms" % r["ms"]) if r["ms"] is not None else "-"
        print("%-34s %-8s %-14s" % (r["name"], r["status"], ms_str), flush=True)
    print("=" * 72, flush=True)
    n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
    n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
    n_skip = sum(1 for r in RESULTS if r["status"] == "SKIP")
    print("PASS=%d FAIL=%d SKIP=%d" % (n_pass, n_fail, n_skip), flush=True)
    print("=" * 72, flush=True)


def main():
    VisPyPatches.apply_patches()

    app_qt = QtWidgets.QApplication(sys.argv)

    # Import App after QApplication exists is not strictly required, but match
    # flatcam.py's general flow.
    from appMain import App

    fc = App(qapp=app_qt)

    # Keep the Python interpreter responsive (mirrors flatcam.py).
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(100)

    def _go():
        try:
            run_probes(app_qt, fc)
        except Exception:
            traceback.print_exc()
        finally:
            # Exit hard instead of QApplication.quit(): quit() triggers the main
            # window close handler, which pops a modal "Save changes?" dialog because
            # loading the sample marked the project dirty. os._exit skips that prompt.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)

    # Give the App a moment to finish its own deferred startup work, then run.
    QTimer.singleShot(2500, _go)

    # Hard-kill fallback in case something hangs.
    def _hard_kill():
        print("[FAIL] hard-kill fallback fired -- harness hung", flush=True)
        os._exit(2)

    QTimer.singleShot(150000, _hard_kill)

    app_qt.exec()
    # Normal, clean exit. We use os._exit to avoid a slow/hanging interpreter
    # shutdown caused by FlatCAM's multiprocessing worker pool. The pickle/
    # DuplicateHandle tracebacks that may print after this are harmless spawn-
    # worker teardown noise -- all measurements have already been printed above.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
