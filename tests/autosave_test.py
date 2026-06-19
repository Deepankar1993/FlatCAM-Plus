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
        rec = a.ensure_recovery_dir(d)
        check(rec == os.path.join(d, "recovery"), "recovery_dir path")
        check(os.path.isdir(rec), "ensure_recovery_dir creates folder")

        sp = a.snapshot_path(d, "20260619_120000")
        check(sp.endswith("autosave_20260619_120000.FlatPrj"), "snapshot_path name")

        for ts in ("20260619_120000", "20260619_120030", "20260619_120100"):
            open(a.snapshot_path(d, ts), "w").close()
        snaps = a.list_snapshots(d)
        check(len(snaps) == 3, "list_snapshots count")
        check(a.newest_snapshot(d).endswith("120100.FlatPrj"), "newest_snapshot")

        a.rotate(d, keep=2)
        snaps = a.list_snapshots(d)
        check(len(snaps) == 2, "rotate keeps 2")
        check(all("120000.FlatPrj" not in s for s in snaps), "rotate dropped oldest")

        check(a.marker_exists(d) is False, "no marker initially")
        a.write_marker(d, a.newest_snapshot(d), "C:/proj.FlatPrj")
        check(a.marker_exists(d) is True, "marker exists after write")
        m = a.read_marker(d)
        check(m["snapshot"].endswith("120100.FlatPrj"), "marker snapshot")
        check(m["project_filename"] == "C:/proj.FlatPrj", "marker project_filename")

        a.write_marker(d, None, None)
        m = a.read_marker(d)
        check(m["snapshot"] is None, "startup marker snapshot None")

        a.clear_recovery(d)
        check(a.list_snapshots(d) == [], "clear_recovery removes snapshots")
        check(a.marker_exists(d) is False, "clear_recovery removes marker")

        # clear_marker removes ONLY the marker, leaving snapshots intact
        open(a.snapshot_path(d, "20260619_130000"), "w").close()
        a.write_marker(d, a.newest_snapshot(d), None)
        a.clear_marker(d)
        check(a.marker_exists(d) is False, "clear_marker removes marker")
        check(len(a.list_snapshots(d)) == 1, "clear_marker keeps snapshots")
        a.clear_recovery(d)  # tidy up for the final missing-marker assertion

        check(a.read_marker(d) is None, "read_marker missing -> None")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("AUTOSAVE TEST: PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)

if __name__ == "__main__":
    run()
