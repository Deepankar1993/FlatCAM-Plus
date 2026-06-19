# tests/

Manual verification harnesses for FlatCAM Plus. There is no automated test suite;
these instantiate the real `App` (a Qt window opens briefly) and exercise hot paths,
then self-quit. They are dev tools, not CI.

Run them with the build virtualenv (the one that has PyQt6/shapely/vispy), from the
**repo root**:

```sh
.venv-build\Scripts\python.exe tests\perf_probe.py
.venv-build\Scripts\python.exe tests\etch_test.py
```

- **perf_probe.py** — loads a sample Gerber and times the interactive hot paths
  (open+parse+plot, a burst of mouse-move events, `info()` status updates, plot-checkbox
  toggle). Prints a PASS/FAIL summary with millisecond timings. Use it to catch
  interactive-performance regressions.
- **etch_test.py** — functional smoke test for the Etch Compensation plugin: a valid
  etch factor creates a `<name>_comp` object; a `0`/negative factor is rejected
  gracefully (no crash). Prints `ETCH TEST: PASS=n FAIL=n`.

Each script puts the repo root on `sys.path` and `chdir`s to it, so it can be launched
from anywhere, and exits via `os._exit` so no "Save changes?" dialog appears.
