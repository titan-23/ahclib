# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`ahclib` is a personal toolkit for AtCoder Heuristic Contest (AHC) problems by titan23. It has two parts:

- **`ahclib/` package** — CLI for parallel test execution, Optuna parameter search, and a Dash-based result dashboard
- **`work/` directory** — the active contest workspace: C++ solver, beam search visualizer, and a C++ include expander

## Common commands

### Initial setup (run once per contest)

```sh
python3 -m ahclib setup    # generates ahc_settings.py in the current working directory
```

### Run parallel tests

```sh
python3 -m ahclib test             # compile + run all test cases in parallel
python3 -m ahclib test --no-compile  # skip recompilation
python3 -m ahclib test --no-verbose  # suppress per-case logging
python3 -m ahclib test --no-record   # don't save per-case stdout/stderr to disk
python3 -m ahclib test -m "memo"     # attach a memo (saved to memo.txt, shown in vis)
```

Compile, verbose logging, and stdout/stderr recording are all **on by default**; the `--no-*` flags disable them. Results and the source snapshot are saved under `./ahclib_results/`.

### Optuna parameter search

```sh
python3 -m ahclib opt              # default (WilcoxonPruner enabled)
python3 -m ahclib opt --no-wilcoxon  # disable pruner
python3 -m ahclib opt -a           # enable auto_sampler
```

The Optuna study is stored in a **local PostgreSQL database** named `ahclib_optuna_<study_name>`, created automatically if absent. The `./ahclib_results/optimizer_results/<study_name>/` directory holds the output (`result.txt` and plot images), not the study DB. An `optuna-dashboard` process is launched automatically and its URL is logged.

### Launch dashboards

```sh
python3 -m ahclib vis    # result history dashboard (reads ./ahclib_results/)
python3 work/vis_beam.py # beam search tree visualizer (reads ./history.json)
```

### Expand C++ includes for submission

```sh
python3 work/cpp_expander.py work/main.cpp          # copies expanded code to clipboard
python3 work/cpp_expander.py work/main.cpp -o a.cpp # writes to file
```

## Configuration (`ahc_settings.py`)

All per-contest settings live in the `AHCSettings` class:

| Field | Purpose |
|---|---|
| `njobs` | Parallel worker count (capped at `cpu_count - 1`) |
| `filename`, `compile_command`, `execute_command` | Build and run commands (`compile_command = None` skips compilation) |
| `input_file_names` | List of test case paths, e.g. `[f"./in/{i:04d}.txt" for i in range(100)]` |
| `timeout` | Per-case timeout in **ms** (`None` = no limit) |
| `is_int` | Whether the score is parsed as `int` (`True`) or `float` (`False`) |
| `direction` | `"minimize"` or `"maximize"`; affects relative-score display and Optuna |
| `get_score(scores)` | Aggregation function (average, geometric mean, etc.) |
| `use_relative_score` | Compute and report relative scores in the log and CSV |
| `pre_dir_name` | Baseline result dir name (under `./ahclib_results/`) used for relative scores |
| `study_name`, `n_trials`, `optuna_timeout`, `njobs_optuna` | Optuna knobs (`optuna_timeout` is in **minutes**, `None` = no limit) |
| `optuna_seed` | Seed for the sampler and for the WilcoxonPruner input-order shuffle |
| `objective(trial)` | Returns a tuple of CLI args passed to the solver as `argv[1], argv[2], …` |
| `optuna_init_trials` | List of param dicts evaluated first (via `study.enqueue_trial`) |
| `optuna_n_startup_trials` | Random-search trial count for `TPESampler` |
| `parse_input_params(file_path)` | Optional; parses problem-specific params for the vis dashboard |
| `vis_beam_input` | Defined in the template; not referenced by the package |

## Score reporting convention

The parallel tester captures the **last line of stderr** and expects the format:

```
Score = <number>
```

Your C++ solver must emit this. Example: `cerr << "Score = " << score << endl;`

## Beam search visualizer (`work/vis_beam.py`)

Reads `history.json` (written by `flying_squirrel::BeamSearchWithTree` when called with `"history.json"` as the filename argument). Displays the full search tree as an interactive Dash/Cytoscape graph.

Key source files:
- `beam_data.py` — loads and processes `history.json`; computes subtree layout, turn stats, snapshot data
- `beam_config.py` — all color theme and Cytoscape stylesheet constants
- `vis_beam.py` — Dash app, callbacks, and layout
- `visualizer.py` — **must be customized per contest**: `generate_board_visual(action_seq)` re-plays moves and renders the board state for the selected node

## C++ solver structure (`work/main.cpp`)

Uses the `titan_cpplib` library (expected at `../../Library_cpp` relative to `work/`). Includes via local paths:

```cpp
#include "titan_cpplib/ahc/beam_search/gemini.cpp"
```

`cpp_expander.py` resolves these includes (searching the paths in `LIB_PATH`) and inlines them into a single file for submission.

The `beam_search` namespace wraps:
- `State` — defines `init()`, `get_actions()`, `try_op()`, `apply_op()`, `rollback()`, `get_state_info()`
- `Action` — carries pre/post score, hash, and turn metadata required by `BeamSearchWithTree`
- `search()` — calls `flying_squirrel::BeamSearchWithTree::search(param, verbose, "history.json")`
