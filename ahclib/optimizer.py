import datetime
import inspect
import json
import multiprocessing
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from logging import basicConfig, getLogger
from typing import Callable, Optional

import optuna
import optunahub
from optuna.storages.journal import JournalFileBackend

from .ahc_settings import AHCSettings
from .ahc_util import to_blue, to_bold, to_green
from .parallel_tester import RESULTS_DIR, ParallelTester, build_tester

logger = getLogger(__name__)

OPTIMIZER_RESULTS_SUBDIR = "optimizer_results"
OPTUNA_JOURNAL_FILE = "optuna-journal.log"
DEFAULT_DASHBOARD_URL = "http://localhost:8080/"
LEGACY_POSTGRES_DB_PREFIX = "ahclib_optuna_"
DASHBOARD_STARTUP_TIMEOUT_SEC = 15


def _configure_logging() -> None:
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )


def _optimizer_results_path() -> str:
    path = os.path.abspath(os.path.join(RESULTS_DIR, OPTIMIZER_RESULTS_SUBDIR))
    os.makedirs(path, exist_ok=True)
    return path


def _journal_path() -> str:
    return os.path.join(_optimizer_results_path(), OPTUNA_JOURNAL_FILE)


def _build_storage() -> optuna.storages.JournalStorage:
    """全 study で共有するローカル JournalStorage を返す"""
    return optuna.storages.JournalStorage(
        JournalFileBackend(file_path=_journal_path())
    )


def _migrate_legacy_postgres_studies(
    target_storage: optuna.storages.BaseStorage,
) -> None:
    """旧版の study 別 PostgreSQL DB を共有 journal へ非破壊でコピーする"""
    try:
        import psycopg2
    except ImportError:
        logger.debug("psycopg2 is unavailable; skipping legacy study migration.")
        return

    try:
        conn = psycopg2.connect(dbname="postgres", connect_timeout=1)
    except psycopg2.Error:
        logger.debug("PostgreSQL is unavailable; skipping legacy study migration.")
        return

    try:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT datname FROM pg_database WHERE left(datname, %s) = %s",
                    (len(LEGACY_POSTGRES_DB_PREFIX), LEGACY_POSTGRES_DB_PREFIX),
                )
                legacy_db_names = [row[0] for row in cur.fetchall()]
        except psycopg2.Error:
            logger.debug(
                "Legacy PostgreSQL databases cannot be listed; skipping migration."
            )
            return
    finally:
        conn.close()

    existing_names = {
        summary.study_name
        for summary in optuna.get_all_study_summaries(storage=target_storage)
    }
    for db_name in legacy_db_names:
        legacy_url = f"postgresql+psycopg2:///{db_name}"
        try:
            summaries = optuna.get_all_study_summaries(storage=legacy_url)
        except Exception as e:
            logger.warning(f"Failed to read legacy Optuna DB {db_name}: {e}")
            continue
        for summary in summaries:
            if summary.study_name in existing_names:
                continue
            try:
                optuna.copy_study(
                    from_study_name=summary.study_name,
                    from_storage=legacy_url,
                    to_storage=target_storage,
                )
            except Exception as e:
                logger.warning(
                    f"Failed to migrate study {summary.study_name} from {db_name}: {e}"
                )
                continue
            existing_names.add(summary.study_name)
            logger.info(
                f"Migrated legacy study {summary.study_name} from {db_name}."
            )


def _start_dashboard() -> subprocess.Popen:
    journal_path = _journal_path()
    executable = shutil.which("optuna-dashboard")
    if executable is None:
        suffix = ".exe" if os.name == "nt" else ""
        executable = os.path.join(
            os.path.dirname(sys.executable), f"optuna-dashboard{suffix}"
        )
    process = subprocess.Popen(
        [executable, journal_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: queue.Queue[Optional[str]] = queue.Queue()

    def _read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.put(line.rstrip())
        stderr_lines.put(None)

    threading.Thread(target=_read_stderr, daemon=True).start()
    deadline = time.monotonic() + DASHBOARD_STARTUP_TIMEOUT_SEC
    dashboard_url = None
    startup_messages: list[str] = []
    while time.monotonic() < deadline:
        try:
            line = stderr_lines.get(timeout=0.1)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        startup_messages.append(line)
        if line.startswith("Listening on "):
            dashboard_url = line.removeprefix("Listening on ").strip()
            break

    if dashboard_url is not None:
        logger.info(f"- dashboard URL : {to_bold(dashboard_url)}")
    elif process.poll() is not None:
        detail = "\n".join(startup_messages) or "no error output"
        raise RuntimeError(f"Optuna Dashboard failed to start: {detail}")
    else:
        logger.warning(
            "Dashboard startup could not be confirmed within %s seconds; expected URL: %s",
            DASHBOARD_STARTUP_TIMEOUT_SEC,
            DEFAULT_DASHBOARD_URL,
        )
    return process


def _stop_dashboard(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _wait_for_dashboard_close() -> None:
    try:
        input(to_bold(to_blue("Press Enter to close the dashboard and exit...")))
    except (EOFError, KeyboardInterrupt):
        pass


def _log_studies(storage: optuna.storages.BaseStorage) -> None:
    summaries = optuna.get_all_study_summaries(storage=storage)
    if summaries:
        logger.info("- studies       : %s", ", ".join(s.study_name for s in summaries))
    else:
        logger.info("- studies       : (none)")


def run_optimizer_dashboard() -> None:
    """最適化は行わず、保存済みの全 study を Dashboard で表示する"""
    _configure_logging()
    storage = _build_storage()
    _migrate_legacy_postgres_studies(storage)
    logger.info("==============================================")
    logger.info(to_bold(to_blue("Optuna Dashboard")))
    logger.info(f"- storage       : {to_bold(_journal_path())}")
    _log_studies(storage)
    process = _start_dashboard()
    logger.info("==============================================")
    try:
        _wait_for_dashboard_close()
    finally:
        _stop_dashboard(process)


class Optimizer:
    def __init__(self, settings: AHCSettings) -> None:
        self.settings: AHCSettings = settings
        self.study_name = settings.study_name
        self.path = _optimizer_results_path()

    @staticmethod
    def _max_optuna_workers(requested: int) -> int:
        available = max(1, multiprocessing.cpu_count() - 1)
        return max(1, min(requested, available))

    @staticmethod
    def _as_execute_args(args) -> tuple:
        return tuple(args)

    def optimize(
        self, sampler: Optional[str] = None, pruner: Optional[str] = None
    ) -> None:
        logger.info("==============================================")
        logger.info(to_bold(to_blue("Optimizer settings:")))
        logger.info(f"- study_name    : {to_bold(self.settings.study_name)}")
        logger.info(f"- direction     : {to_bold(self.settings.direction)}")
        logger.info(f"- n_trials      : {to_bold(self.settings.n_trials)}")
        optuna_timeout_min = self.settings.optuna_timeout
        optuna_timeout = (
            optuna_timeout_min * 60 if optuna_timeout_min is not None else None
        )
        logger.info(f"- timeout [min] : {to_bold(optuna_timeout_min)}")

        started_at = datetime.datetime.now().astimezone()
        start = time.time()

        def _objective(trial: optuna.trial.Trial) -> float:
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            args = self._as_execute_args(self.settings.objective(trial))
            trial.set_user_attr("ahclib_execute_args", [str(arg) for arg in args])
            tester.append_execute_command(args)
            scores = tester.run()
            trial.set_user_attr("ahclib_evaluated_cases", len(scores))
            trial.set_user_attr("ahclib_wilcoxon_stopped", False)
            return tester.get_score(scores)

        def _objective_wilcoxon_pruner(trial: optuna.trial.Trial) -> float:
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            args = self._as_execute_args(self.settings.objective(trial))
            trial.set_user_attr("ahclib_execute_args", [str(arg) for arg in args])
            tester.append_execute_command(args)
            result = tester.run_opt_pruner(trial)
            completed_scores = [
                score for score in result.scores if score is not None
            ]
            trial.set_user_attr("ahclib_evaluated_cases", result.completed_count)
            trial.set_user_attr("ahclib_wilcoxon_stopped", result.pruned)

            # WilcoxonPruner では、途中結果を TrialPruned として捨てず、
            # 完了済み instance から推定した最終値を返すことが推奨されている。
            score = tester.get_score(completed_scores)
            if result.pruned:
                width = len(str(len(result.scores)))
                logger.info(
                    to_green(
                        "wilcoxon stop | "
                        f"{str(result.completed_count).zfill(width)} / "
                        f"{len(result.scores)} | estimated score: {score}"
                    )
                )
            return score

        storage = _build_storage()
        _migrate_legacy_postgres_studies(storage)
        objective_func: Callable[[optuna.trial.Trial], float] = _objective

        optuna_seed = self.settings.optuna_seed
        if sampler == "auto_sampler":
            optuna_sampler = optunahub.load_module("samplers/auto_sampler").AutoSampler(
                seed=optuna_seed
            )
        else:
            sampler = "TPESampler"
            optuna_sampler = optuna.samplers.TPESampler(
                multivariate=True,
                n_startup_trials=self.settings.optuna_n_startup_trials,
                seed=optuna_seed,
            )
        logger.info(f"- sampler       : {to_bold(sampler)}")

        optuna_pruner = None
        if pruner == "WilcoxonPruner":
            logger.info(f"- pruner        : {to_bold(pruner)}")
            optuna_pruner = optuna.pruners.WilcoxonPruner(p_threshold=0.1)
            objective_func = _objective_wilcoxon_pruner

        study: optuna.Study = optuna.create_study(
            direction=self.settings.direction,
            study_name=self.settings.study_name,
            storage=storage,
            load_if_exists=True,
            sampler=optuna_sampler,
            pruner=optuna_pruner,
        )

        initial_trial_count = len(study.trials)
        for params in self.settings.optuna_init_trials:
            study.enqueue_trial(params, skip_if_exists=True)

        process: Optional[subprocess.Popen] = None
        try:
            logger.info("------------------------------------------")
            _log_studies(storage)
            process = _start_dashboard()
            logger.info("==============================================")

            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            tester.compile()
            study.optimize(
                objective_func,
                n_trials=self.settings.n_trials,
                timeout=optuna_timeout,
                n_jobs=self._max_optuna_workers(self.settings.njobs_optuna),
            )

            try:
                logger.info(study.best_trial)
            except ValueError:
                logger.warning("The study has no completed trials.")
            logger.info("writing results ...")
            finished_at = datetime.datetime.now().astimezone()
            self.output_study(
                study,
                run_info={
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat(),
                    "elapsed_seconds": time.time() - start,
                    "sampler": sampler,
                    "pruner": pruner,
                    "requested_n_trials": self.settings.n_trials,
                    "trials_before_run": initial_trial_count,
                    "trials_after_run": len(study.trials),
                },
            )
            logger.info(
                f"Finish parameter searching. Time: {time.time() - start:.2f}sec."
            )
            _wait_for_dashboard_close()

        except Exception:
            logger.exception("Optimizer failed.")
            raise
        finally:
            if process is not None:
                _stop_dashboard(process)

    def _copy_snapshot(self, source: Optional[str], output_dir: str) -> None:
        if not source or not os.path.isfile(source):
            return
        destination = os.path.join(output_dir, os.path.basename(source))
        try:
            if os.path.exists(destination) and os.path.samefile(source, destination):
                return
            shutil.copy2(source, destination)
        except OSError as e:
            logger.warning(f"Failed to copy {source}: {e}")

    def _output_plots(self, study: optuna.Study, img_path: str) -> None:
        plots = {
            "contour": optuna.visualization.plot_contour,
            "param_importances": optuna.visualization.plot_param_importances,
            "edf": optuna.visualization.plot_edf,
            "optimization_history": optuna.visualization.plot_optimization_history,
            "parallel_coordinate": optuna.visualization.plot_parallel_coordinate,
            "slice": optuna.visualization.plot_slice,
        }
        for filename, plot_func in plots.items():
            try:
                fig = plot_func(study)
                fig.write_html(os.path.join(img_path, f"{filename}.html"))
                try:
                    fig.write_image(os.path.join(img_path, f"{filename}.png"))
                except (ValueError, RuntimeError, OSError) as e:
                    logger.debug(f"Failed to write {filename}.png: {e}")
            except (ValueError, RuntimeError) as e:
                logger.warning(f"Failed to create {filename} plot: {e}")

    def output_study(
        self, study: optuna.Study, run_info: Optional[dict] = None
    ) -> None:
        path = os.path.join(self.path, self.study_name)
        os.makedirs(path, exist_ok=True)
        run_metadata = dict(run_info or {})
        run_id = None
        if run_info is not None:
            run_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            run_metadata["run_id"] = run_id

        try:
            best_trial = study.best_trial
        except ValueError:
            best_trial = None

        with open(os.path.join(path, "result.txt"), "w", encoding="utf-8") as f:
            if best_trial is None:
                print("No completed trials.", file=f)
            else:
                print(best_trial, file=f)

        study.trials_dataframe().to_csv(
            os.path.join(path, "trials.csv"), index=False
        )
        trial_counts: dict[str, int] = {}
        for trial in study.trials:
            state = trial.state.name
            trial_counts[state] = trial_counts.get(state, 0) + 1
        summary = {
            "study_name": study.study_name,
            "direction": study.direction.name.lower(),
            "trial_counts": trial_counts,
            "best_trial": (
                None
                if best_trial is None
                else {
                    "number": best_trial.number,
                    "value": best_trial.value,
                    "params": best_trial.params,
                    "user_attrs": best_trial.user_attrs,
                }
            ),
            "run": run_metadata,
        }
        with open(os.path.join(path, "study.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

        self._copy_snapshot(self.settings.filename, path)
        try:
            settings_source = inspect.getsourcefile(self.settings)
        except TypeError:
            settings_source = None
        self._copy_snapshot(settings_source, path)

        # study 直下は最新状態として更新しつつ、tester と同様に各実行時点の
        # trial 一覧・metadata・source を timestamp 付きで保存する。
        if run_id is not None:
            run_path = os.path.join(path, "runs", run_id)
            os.makedirs(run_path, exist_ok=False)
            for filename in ("result.txt", "trials.csv", "study.json"):
                shutil.copy2(os.path.join(path, filename), run_path)
            self._copy_snapshot(self.settings.filename, run_path)
            self._copy_snapshot(settings_source, run_path)

        img_path = os.path.join(path, "images")
        os.makedirs(img_path, exist_ok=True)
        self._output_plots(study, img_path)


def run_optimizer(settings: AHCSettings, sampler=None, pruner=None) -> None:
    _configure_logging()
    optimizer = Optimizer(settings)
    optimizer.optimize(sampler, pruner)


if __name__ == "__main__":
    run_optimizer(AHCSettings)
