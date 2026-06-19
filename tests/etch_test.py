#!/usr/bin/env python3
"""
etch_test.py -- Functional smoke test for the Etch Compensation plugin.

Instantiates the REAL App (PyQt6), loads a sample Gerber, and exercises
ToolEtchCompensation.on_compensate() to verify:

  A. A valid Etch Factor produces a new "<name>_comp" Gerber object.
  B. An Etch Factor of 0 does NOT crash (the old code raised ZeroDivisionError
     via `etch_factor = 1 / factor_value`) and creates no object.
  C. A negative Etch Factor is rejected (would otherwise shrink the copper).

Run with the venv that has the deps:

    .venv-build\\Scripts\\python.exe etch_test.py

Exits via os._exit so no "Save changes?" dialog appears. Does NOT modify any
application source.
"""

import os
import sys
import traceback

# This harness lives in tests/ but drives the app package at the repo root. Put the
# repo root (parent of this folder) on sys.path so `appMain`/`appGUI` import, and chdir
# to it so the app's CWD-relative resource paths (assets/resources, ...) resolve.
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6 import QtWidgets
from PyQt6.QtCore import QTimer

from appGUI import VisPyPatches

RESULTS = []


def record(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print("[%-4s] %-40s %s" % (status, name, detail), flush=True)


def _pump(app_qt, n=8):
    for _ in range(n):
        app_qt.processEvents()


def run_tests(app_qt, fc):
    sample = os.path.join(ROOT, "assets", "examples", "files", "test.gbr")

    # ----- load the sample gerber -----
    name = None
    try:
        before = set(fc.collection.get_names())
        fc.f_handlers.open_gerber(sample, plot=True)
        _pump(app_qt)
        new_names = set(fc.collection.get_names()) - before
        if not new_names:
            record("load_sample_gerber", "FAIL", "no object loaded")
            return
        name = list(new_names)[0]
        record("load_sample_gerber", "PASS", "object: %s" % name)
    except Exception as e:
        record("load_sample_gerber", "FAIL", repr(e))
        traceback.print_exc()
        return

    etch = fc.etch_tool

    def setup_ui(factor_text):
        # Build/refresh the plugin UI, then select the source object + factor mode.
        etch.run(toggle=False)
        etch.ui.gerber_combo.set_value(name)
        etch.ui.ratio_radio.set_value('factor')
        etch.ui.thick_entry.set_value(18.0)
        etch.ui.factor_entry.set_value(factor_text)

    # ----- A: valid etch factor -> new "_comp" object -----
    try:
        setup_ui('2.0')
        before = set(fc.collection.get_names())
        etch.on_compensate()
        _pump(app_qt, 30)
        created = set(fc.collection.get_names()) - before
        comp = [n for n in created if n.endswith("_comp")]
        if comp:
            record("A_valid_factor_creates_object", "PASS", "created: %s" % comp[0])
        else:
            record("A_valid_factor_creates_object", "FAIL",
                   "no *_comp object created (got: %s)" % sorted(created))
    except Exception as e:
        record("A_valid_factor_creates_object", "FAIL", repr(e))
        traceback.print_exc()

    # ----- B: factor 0 must not crash (old: ZeroDivisionError) -----
    try:
        setup_ui('0')
        before = set(fc.collection.get_names())
        etch.on_compensate()           # must return gracefully, NOT raise
        _pump(app_qt, 10)
        created = set(fc.collection.get_names()) - before
        if not created:
            record("B_zero_factor_no_crash", "PASS", "graceful reject, no object")
        else:
            record("B_zero_factor_no_crash", "FAIL",
                   "unexpectedly created: %s" % sorted(created))
    except ZeroDivisionError as e:
        record("B_zero_factor_no_crash", "FAIL", "ZeroDivisionError: %s" % e)
    except Exception as e:
        record("B_zero_factor_no_crash", "FAIL", repr(e))
        traceback.print_exc()

    # ----- C: negative factor rejected -----
    try:
        setup_ui('-2.0')
        before = set(fc.collection.get_names())
        etch.on_compensate()
        _pump(app_qt, 10)
        created = set(fc.collection.get_names()) - before
        if not created:
            record("C_negative_factor_rejected", "PASS", "graceful reject, no object")
        else:
            record("C_negative_factor_rejected", "FAIL",
                   "unexpectedly created: %s" % sorted(created))
    except Exception as e:
        record("C_negative_factor_rejected", "FAIL", repr(e))
        traceback.print_exc()

    # ----- summary -----
    print("\n" + "=" * 64, flush=True)
    n_pass = sum(1 for _, s, _ in RESULTS if s == "PASS")
    n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print("ETCH TEST: PASS=%d FAIL=%d" % (n_pass, n_fail), flush=True)
    print("=" * 64, flush=True)


def main():
    VisPyPatches.apply_patches()
    app_qt = QtWidgets.QApplication(sys.argv)
    from appMain import App
    fc = App(qapp=app_qt)

    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(100)

    def _go():
        try:
            run_tests(app_qt, fc)
        except Exception:
            traceback.print_exc()
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)

    QTimer.singleShot(2500, _go)

    def _hard_kill():
        print("[FAIL] hard-kill fallback fired -- harness hung", flush=True)
        os._exit(2)

    QTimer.singleShot(120000, _hard_kill)
    app_qt.exec()
    os._exit(0)


if __name__ == "__main__":
    main()
