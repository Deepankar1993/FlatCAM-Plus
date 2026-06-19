# GitHub Auto-Updater — Design Spec

**Date:** 2026-06-19
**Component:** FlatCAM Evo (PyQt6 desktop CAM app)
**Status:** Approved for implementation planning

## Goal

Give FlatCAM Plus (this fork, currently Beta 8.998) a working, fork-aware update
mechanism that:

- Checks the fork's own GitHub Releases (`github.com/Deepankar1993/FlatCAM-Plus/releases`)
  once per launch, on a worker thread, shortly after startup.
- For an **installed Windows .exe** build, performs a **fully automatic** download +
  silent re-install + relaunch (with a brief non-blocking toast), so beta users stay
  current without manual steps.
- For **source** or **portable** installs, **detects and links only** — a non-blocking
  notice with release notes and a link to the releases page (plus a
  `git fetch --tags && git pull` hint for source clones).
- Replaces the dead, upstream-pointed `flatcam.org` version check.

The work is isolated in a new `appHandlers/appUpdate.py` (an `AppUpdate` QObject),
mirroring how auto-save/recovery was isolated in `appHandlers/appAutoSave.py`.

## Why the current implementation is insufficient

The existing version-check is dead code for this fork on three independent counts,
all verified in the source:

1. **It never runs in a beta build.** The startup gate at `appMain.py:1105` is:

   ```python
   if (self.beta is False or self.beta is None) and self.options["global_version_check"] is True:
       ...
       self.worker_task.emit({'fcn': self.version_check, 'params': []})
   ```

   But `App.beta = True` (`appMain.py:184`) and `App.version = 8.998`
   (`appMain.py:181`). Since `beta` is `True`, the condition is `False` and
   `version_check()` is **never dispatched**. Every release of this fork ships as a
   beta, so the check is permanently disabled by construction.

2. **It points at the wrong (upstream, dead) domain.** `version_check()`
   (`appMain.py:7268`) builds its URL from `App.version_url = "http://flatcam.org/version"`
   (`appMain.py:196`) and `urllib.request.urlopen`s it (`appMain.py:7299`). That is the
   *upstream* FlatCAM project's host (plain HTTP, no longer serving update JSON for this
   fork), not the fork at `github.com/Deepankar1993/FlatCAM-Plus`. Even if the gate
   passed, it would query the wrong project and could never see the fork's releases.

3. **Its version comparison is numeric/string and fork-unaware.** At `appMain.py:7318`
   it does `if self.version >= data["version"]:` where `self.version` is a Python
   `float` (`8.998`). A float comparison cannot model tagged release semantics
   (`v8.998.1`, `v8.999-beta2`), and the fork's installer version is a dotted string
   (`MyAppVersion "8.998.1"` in `installer_windows.iss:6`) that does not even parse as a
   float. The check also routes results through a stats-gated path (it only builds the
   "real" URL when `send_stats_cb` is on, `appMain.py:7279`), conflating telemetry with
   update checking.

Supporting facts that constrain the replacement:

- **About box already links the fork.** `appMain.py:3027-3030` and `3044-3045` already
  hard-code `https://github.com/Deepankar1993/FlatCAM-Plus`, `.../releases`, and
  `.../issues`. The updater should reuse these constants, not invent new ones.
- **Settings key exists but is mis-scoped.** `defaults.py:91` has
  `"global_version_check": True`, surfaced in Preferences via
  `PreferencesUIManager.py:70` → `version_check_cb` (defined
  `GeneralAppPrefGroupUI.py:262`, tooltip "check for a new version automatically at
  startup"). It is currently chained to `send_stats_cb` through an
  `OptionalInputSection` (`GeneralAppPrefGroupUI.py:279`), tying update-checking to
  telemetry.

**Decision on `global_version_check`:** retire it as the *gate symbol* and introduce a
clearly-named `global_update_check` (below). The old `version_check_cb`/`ois_version_check`
UI and the `flatcam.org` `version_check()` method are removed. We keep
`global_send_stats`/`send_stats_cb` independent (no longer entangled via
`OptionalInputSection`). Rationale: repurposing a float-era, telemetry-coupled key
in-place is more confusing than a clean rename, and the rename makes the Preferences
UI honest about what it does.

## Decisions (locked)

- **Update source:** the fork's GitHub Releases API,
  `https://api.github.com/repos/Deepankar1993/FlatCAM-Plus/releases`. Pick the
  **newest release tag including pre-releases** (the fork ships betas); compare to the
  running version.
- **Behavior by install type:**
  - **Installed Windows .exe → fully automatic.** Detected via `sys.frozen` **and** an
    installer marker (Inno Setup uninstall registry key). Download the release's
    `*_setup.exe` asset on a worker thread (with progress), then launch it with Inno
    **silent** flags and quit, so it upgrades and relaunches. Show a brief non-blocking
    "Updating to vX, restarting…" toast.
  - **Source or portable → detect + link only.** Non-blocking notice with release
    notes + link to the releases page; for source installs also show the
    `git fetch --tags && git pull` hint. No auto-apply.
- **Cadence:** once per launch, on a worker thread, shortly after startup. No periodic
  timer, no Help-menu manual check.
- **Trust / security:** download **only** from the official repo's release assets over
  **HTTPS**; verify SHA256 against a checksum file in the release **when present**, but
  do not require it. Only ever launch executables originating from those official HTTPS
  release assets.
- **Required installer change:** `installer_windows.iss` must gain `AppMutex` +
  `CloseApplications` / `RestartApplications` so it can upgrade a running app.
- **New settings (in `defaults.py` `factory_defaults`):**
  - `global_update_check` (bool, default `True`)
  - `global_update_auto_install` (bool, default `True`; when off, the installed-exe path
    falls back to notify-only)
  - `global_update_include_prerelease` (bool, default `True`)
  - `global_update_skipped_version` (str, default `""`; for "skip this version")
- **New module:** `appHandlers/appUpdate.py` (`AppUpdate` QObject). It **replaces** the
  dead `flatcam.org` `version_check()`.

## Architecture & Components

| Unit | Location | Responsibility |
|---|---|---|
| `AppUpdate` (new class, QObject) | `appHandlers/appUpdate.py` (new) | Owns install-type detection, the GitHub Releases query, version comparison, asset selection + SHA256 verification, the download-with-progress, the silent-install launch, and all notify-only messaging. Receives `app` in its constructor like the other handlers. |
| Constants | `appMain.py` (`App` class attrs) | Add `update_repo = "Deepankar1993/FlatCAM-Plus"`, `update_api_url = "https://api.github.com/repos/%s/releases" % update_repo`, `releases_url = "https://github.com/%s/releases" % update_repo`. Reuse, do not duplicate, the About-box repo URL (`appMain.py:3027`). |
| Settings | `defaults.py` | Add the four `global_update_*` keys near `defaults.py:91`; **remove** `global_version_check`. |
| Preferences UI | `appGUI/preferences/general/GeneralAppPrefGroupUI.py` | Replace `version_check_cb`/`ois_version_check` (lines 262-279) with an "Updates" block: `update_check_cb` (Check for updates at startup), `update_auto_install_cb` (Auto-install updates — installed Windows only), `update_prerelease_cb` (Include beta/pre-release versions). Keep `send_stats_cb` standalone. |
| Preferences binding | `appGUI/preferences/PreferencesUIManager.py` | Replace the `"global_version_check"` mapping (line 70) with mappings for `global_update_check`, `global_update_auto_install`, `global_update_include_prerelease`. `global_update_skipped_version` is not user-facing (set programmatically by the "Skip this version" button in the notice). |
| Startup wiring | `appMain.py` ~line 1100-1109 | Replace the dead `beta is False` gate and `version_check` dispatch with: `if self.options["global_update_check"]: self.app_update = AppUpdate(self); self.worker_task.emit({'fcn': self.app_update.check, 'params': []})`. |
| Removal | `appMain.py` | Delete `version_check()` (lines 7268-7330) and the `version_url` attribute (line 196); leave `app_url`/`manual_url` intact. |
| Installer | `installer_windows.iss` | Add `AppMutex`, `CloseApplications=yes`, `RestartApplications=yes`, `RestartApplicationsAfterInstall=yes` to `[Setup]` (details below). |
| Build | `build_windows.ps1` | No behavioral change required; document that the produced asset name (`FlatCAM_Plus_<ver>_beta_setup.exe`, from `installer_windows.iss:27`) is what the updater matches against. Optionally emit a `SHA256SUMS.txt` alongside the installer for the opt-in checksum verification. |

### Install-type detection

`AppUpdate.detect_install_type()` returns one of `"installed_exe"`, `"portable"`,
`"source"`:

- **frozen?** `getattr(sys, "frozen", False)` — the same idiom already used at
  `appMain.py:4026` and `appHandlers/appIO.py:1018`. If not frozen → `"source"`.
- **portable?** Re-use the resolved portable flag the app already computes from
  `config/configuration.txt` (`portable=True`); see `flatcam.py:54-64` and the mirror in
  `appMain.py:499-518`. `AppUpdate` reads `self.app.options["global_portable"]`
  (`defaults.py:83`) rather than re-parsing the file. If frozen **and** portable →
  `"portable"`.
- **installed?** If frozen and not portable, confirm an installer footprint: read the
  Inno Setup per-app uninstall key under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{81283BD6-825F-4D4E-815D-A58B437FFEEE}_is1`
  (and the `HKLM` equivalent for an all-users install) — the AppId is
  `{{81283BD6-825F-4D4E-815D-A58B437FFEEE}` from `installer_windows.iss:12`, and Inno
  suffixes `_is1`. Present → `"installed_exe"`. Absent (frozen, non-portable, but no
  uninstall key — e.g. a hand-unzipped dist) → treat as `"portable"` (notify-only),
  which is the safe fallback.

### Version-comparison strategy (date-based)

The running build cannot encode the "(update N)" patch level: `App.version` is the
float `8.998` (`appMain.py:181`) and there is **no build/update counter** anywhere in
the app. The one fine-grained, already-maintained signal the build carries is
`App.version_date` (`"2026/6/17"`, `appMain.py:183`). GitHub stamps every release with
an automatic, monotonic `published_at` timestamp. **The updater therefore decides
"newer" by date, not by version number** (confirmed with the maintainer: release names
like "FlatCAM Plus 8.998 BETA (update 1)" are not semver and do not map onto the float).

- Parse `App.version_date` with a tolerant `%Y/%m/%d` parse (single-digit month/day, no
  leading zeros) into a `datetime.date`. A parse failure → treat the build date as
  unknown and behave conservatively (notify-only at most, never auto-install; log it).
- Parse each candidate release's `published_at` (ISO-8601 UTC, e.g. `2026-06-18T...Z`)
  into a `date`. Drafts have a null `published_at` and are already filtered out.
- A release is **newer iff** its `published_at` date is **strictly greater** than the
  build's `version_date`. Equal dates → **not newer** (prevents same-day re-prompting).
- The release **tag** (`v8.998.2-beta`, `vMAJOR.MINOR.PATCH-beta`) and **name**
  ("FlatCAM Plus 8.998 BETA (update 1)") are used **only** for display and as the
  identity for "skip this version" (`global_update_skipped_version` stores the tag) —
  **never** for the newer/older decision.

**Why date-based:** the "(update N)" naming cannot be told apart by the `8.998` float, so
a numeric compare cannot distinguish two updates of the same line. `published_at` vs
`version_date` is automatic, monotonic across updates, and needs no new version field in
the app.

**Known limitation:** two releases published on the *same calendar day* are
indistinguishable by date; the second would not be auto-detected until the next day.
Acceptable for a once-per-launch desktop check; "skip this version" and the next build's
date bump cover the gap. (If finer resolution is ever needed, compare the full
`published_at` timestamp against a build timestamp — out of scope here.)

**Release prerequisite:** every release build MUST bump `App.version_date`
(`appMain.py:183`) to its build date — this is the existing project convention and is
exactly what makes date comparison correct. Keeping `installer_windows.iss`
`MyAppVersion` and the git tag consistent remains good practice for display, but is not
used for detection.

### Release / asset selection

1. `GET {update_api_url}` (unauthenticated) → JSON array of releases.
2. Filter: if `global_update_include_prerelease` is `False`, drop entries where
   `prerelease == true` and drop `draft == true` always.
3. Sort the remaining by `published_at` (newest first); take the newest. (GitHub
   returns newest-first, but we sort defensively rather than trusting order.)
4. If `tag == global_update_skipped_version` → no-op (user chose to skip this exact
   version).
5. If the newest release's `published_at` date is **not strictly after** the build's
   `version_date` → log "up to date", no UI.
6. Else hand `{tag, name, body (release notes), html_url, assets[]}` to the
   behavior dispatcher.

For the installed-exe path, pick the asset whose name matches `*_setup.exe` (if none is present, the path falls back to notify-only — see “Installer-asset availability” below)
(the `OutputBaseFilename` pattern `FlatCAM_Plus_<ver>_beta_setup`,
`installer_windows.iss:27`). If a checksum asset (`SHA256SUMS.txt` or `<asset>.sha256`)
is present, remember its `browser_download_url` for verification.

### Installer-asset availability (current state & prerequisite)

**The auto-install path only fires when the matched release actually ships a `*_setup.exe` asset.** As of this writing the latest release `v8.998.2-beta` has **no installer asset** attached, so even on an installed Windows build the updater must degrade to **notify-only** for it rather than attempt (and fail) a download.

Hard rule, enforced in `select_asset()`:

- Installed-exe path + a `*_setup.exe` asset present → auto-install.
- Installed-exe path + **no** `*_setup.exe` asset → **notify-only** (same notice as source/portable: release notes + releases link). Never start a partial download, never error, never block — just log "no installer asset; notify-only".
- The matched release is still surfaced to the user (they learn a newer version exists and can grab it from the releases page) regardless of asset availability.

**Release prerequisite to “light up” hands-off updates:** future releases must upload the installer produced by `build_windows.ps1 -Installer` (`FlatCAM_Plus_<ver>_beta_setup.exe`, per `installer_windows.iss:27`) as a GitHub release asset, optionally alongside a `SHA256SUMS.txt` for the opt-in checksum verification. Until then the updater is fully functional but operates in notify-only mode for every release — which is the correct, safe behavior, not a bug.

### Installer changes (`installer_windows.iss`)

Add to `[Setup]`:

```
AppMutex=FlatCAMPlus_SingleInstance
CloseApplications=yes
RestartApplications=yes
RestartApplicationsAfterInstall=yes
```

The running app must create/hold a named mutex matching `AppMutex` so Inno can detect a
running instance and close/restart it during a silent upgrade. `AppUpdate` (Windows
only) creates the Win32 named mutex `FlatCAMPlus_SingleInstance` at construction (via
`ctypes.windll.kernel32.CreateMutexW`) and holds the handle for process lifetime. The
silent-install launch uses Inno's flags: `/SILENT /SUPPRESSMSGBOXES /NORESTART
/CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`. `RestartApplicationsAfterInstall=yes` plus the
existing `[Run]` entry (`installer_windows.iss:49`, which has `skipifsilent`) means
relaunch is driven by `RestartApplications`, not the post-install `[Run]` step.

## Data flow

**Once-per-launch check (worker thread):**

1. Startup (`appMain.py` ~1105, replacing the dead gate): if
   `global_update_check` is on, instantiate `AppUpdate` and
   `self.worker_task.emit({'fcn': self.app_update.check, 'params': []})` — the same
   worker-dispatch idiom the old code used at `appMain.py:1109`.
2. On the worker: `detect_install_type()`, then HTTPS `GET` the Releases API, parse,
   select newest, compare. All network/parse work stays off the GUI thread.
3. Result is reported to the GUI **only via Qt signals** — `self.app.inform.emit(...)`
   for the status-bar toast (`inform` is defined `appMain.py:223`) and
   `self.app.message.emit(title, body, "info")` for the richer notice
   (`message` defined `appMain.py:258`). The worker never touches widgets directly.

**Notify-only path (source / portable, or installed with `auto_install` off):**

4. Emit a non-blocking notice: release name + notes (`body`) + a clickable link to
   `releases_url`. For `"source"`, append the `git fetch --tags && git pull` hint. The
   notice offers "Skip this version" (sets `global_update_skipped_version = tag`) and
   "Open releases page".

**Auto-install path (installed_exe + `global_update_auto_install` True):**

5. Resolve the `*_setup.exe` asset's `browser_download_url`; assert the host is
   `github.com`/`objects.githubusercontent.com` over HTTPS (reject anything else).
6. Download to a temp file on the worker thread, emitting periodic progress through
   `inform` (e.g. "Downloading update… 42%").
7. If a checksum asset is present, download it and verify the file's SHA256; mismatch →
   abort, delete the temp file, log, and fall back to the notify-only notice. Absent →
   proceed (verification is opt-in, not required).
8. Emit the non-blocking toast "Updating to v<tag>, restarting…" via `inform`.
9. Launch the verified setup exe with the silent flags (`subprocess`/`os.startfile`),
   then trigger a clean application quit so Inno can replace files behind the held
   `AppMutex` and relaunch via `RestartApplications`.

## Error handling

- **Offline / DNS / timeout / non-200:** caught, logged once to `log.txt` via
  `self.app.log` (the existing logger; cf. `appMain.py:1610` `log.txt` path), **silent
  no-op** — no nag dialog. This is the explicit behavioral fix versus the old code,
  which emitted `[WARNING_NOTCL]`/`[ERROR_NOTCL]` toasts on every failure
  (`appMain.py:7303`, `7310`).
- **GitHub rate limit:** unauthenticated API is 60 requests/hour per IP; once-per-launch
  is far under budget. On HTTP 403 with `X-RateLimit-Remaining: 0`, treat as a transient
  error: log and no-op (no retry, no auth token — we never embed credentials).
- **Malformed JSON / unparseable tag:** log and no-op (never raise into the worker pool).
- **Download failure / checksum mismatch / asset not found:** abort the auto-install,
  clean up temp files, log, and **degrade gracefully** to the notify-only notice with
  the releases link.
- **Non-Windows or non-frozen reaching the install path:** impossible by detection, but
  guarded — any unexpected type falls back to notify-only.
- All `AppUpdate` public entry points are wrapped so an exception on the worker thread is
  logged and swallowed; an update check must never crash or block startup.

## Testing strategy (manual — repo has no automated suite)

1. **Source install, newer release present:** run from source with
   `global_update_check` on; confirm a non-blocking notice with release notes, a
   working releases-page link, and the `git fetch --tags && git pull` hint; confirm **no
   download** occurs.
2. **Up to date:** point at a release equal to/older than `App.version`; confirm a log
   line and **no UI**.
3. **Date compare:** unit-exercise the comparator: build `version_date` `2026/6/17`
   vs release `published_at` `2026-06-18` (newer), `2026-06-17` (equal → not newer),
   `2026-06-16` (older), and a malformed `version_date`/`published_at` (→ treated as
   not-newer / notify-only, never auto-install).
4. **Pre-release toggle:** with `global_update_include_prerelease` off, confirm
   pre-release tags are ignored; on, confirm the newest beta is selected.
5. **Skip version:** click "Skip this version"; relaunch; confirm the same version no
   longer notifies, but a newer one does.
6. **Installed exe, auto-install on:** build with `build_windows.ps1 -Installer`, install
   via the setup exe, publish a newer release; launch; confirm the progress toast, the
   "Updating to v<tag>, restarting…" toast, silent re-install, and automatic relaunch on
   the new version (validates the new `AppMutex`/`CloseApplications`/`RestartApplications`
   settings against a running instance).
7. **Installed exe, auto-install off:** same setup with `global_update_auto_install`
   off; confirm it degrades to notify-only.
8. **Portable:** mark `portable=True` in `config/configuration.txt`; confirm detection as
   portable and notify-only behavior (no download).
9. **Checksum:** publish a release with a `SHA256SUMS.txt`; confirm verification passes;
   then corrupt the file/checksum and confirm abort + fallback notice.
10. **Offline:** disconnect network; confirm a single `log.txt` entry and no UI, no
    startup delay.

## Out of scope / non-goals

- Periodic/background re-checks or a Help-menu "Check for updates" action (cadence is
  strictly once per launch).
- macOS/Linux auto-install (those platforms get notify-only; the silent-installer path is
  Windows/Inno-specific).
- Code signing of the installer or signature verification beyond opt-in SHA256.
- Authenticated GitHub API access or higher rate limits.
- In-place patching/delta updates, or updating a source clone automatically (we only show
  the `git` hint).
- Migrating or preserving the old `flatcam.org` telemetry (`global_send_stats` stays as a
  separate, untouched feature).
- Changing `App.version` from a float to a string (the updater normalizes around the
  existing float; a future cleanup, not part of this feature).
