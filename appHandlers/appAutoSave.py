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


def clear_marker(data_path):
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
        self._exiting = False

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
        self._exiting = True
        try:
            clear_recovery(self.data_path)
        except OSError:
            self.app.log.error("AppAutoSave.mark_clean_exit() failed:\n%s" % traceback.format_exc())

    def drop_marker(self):
        """Remove only the session marker, keeping snapshots on disk."""
        try:
            clear_marker(self.data_path)
        except OSError:
            self.app.log.error("AppAutoSave.drop_marker() failed:\n%s" % traceback.format_exc())

    # ----- snapshot -----
    def do_snapshot(self):
        if self._exiting:
            return
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
        if self._exiting:
            return
        try:
            self.app.f_handlers.save_project(path, silent=True)
            write_marker(self.data_path, path, self.app.project_filename)
            keep = int(self.app.options.get('global_autosave_keep', 10))
            rotate(self.data_path, keep)
            # inform is a Qt signal => safe to emit from a worker thread
            self.app.inform.emit('[success] %s' % _("Auto-saved"))
        except Exception:
            self.app.log.error("AppAutoSave._snapshot_worker() failed:\n%s" % traceback.format_exc())
