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
python3 -m ahclib test -r          # save all stdout/stderr to disk
```

Results and the source snapshot are saved under `./ahclib_results/`.

### Optuna parameter search

```sh
python3 -m ahclib opt              # default (WilcoxonPruner enabled)
python3 -m ahclib opt --no-wilcoxon  # disable pruner
python3 -m ahclib opt -a           # enable auto_sampler
```

Optuna DB is stored at `./ahclib_results/optimizer_results/`.

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
| `filename`, `compile_command`, `execute_command` | Build and run commands |
| `input_file_names` | List of test case paths, e.g. `[f"./in/{i:04d}.txt" for i in range(100)]` |
| `timeout` | Per-case timeout in **ms** (`None` = no limit) |
| `get_score(scores)` | Aggregation function (average, geometric mean, etc.) |
| `direction` | `"minimize"` or `"maximize"` for Optuna |
| `study_name`, `n_trials`, `njobs_optuna` | Optuna knobs |
| `objective(trial)` | Returns a tuple of CLI args passed to the solver as `argv[1], argv[2], …` |
| `parse_input_params(file_path)` | Optional; parses problem-specific params for the vis dashboard |

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
