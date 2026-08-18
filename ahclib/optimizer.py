import datetime
import inspect
import json
import multiprocessing
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import warnings
from logging import getLogger
from typing import Any, Callable, Iterable, Optional, TypeVar

import optuna
import optunahub
from optuna.storages.journal import JournalFileBackend, JournalFileOpenLock

from .ahc_settings import AHCSettings
from .ahc_util import to_blue, to_bold, to_green
from .logging_util import configure_elapsed_logging
from .parallel_tester import RESULTS_DIR, ParallelTester, build_tester
from .tailscale_serve import TailscaleServe

logger = getLogger(__name__)
FactoryResult = TypeVar("FactoryResult")

OPTIMIZER_RESULTS_SUBDIR = "optimizer_results"
OPTUNA_JOURNAL_FILE = "optuna-journal.log"
LEGACY_POSTGRES_DB_PREFIX = "ahclib_optuna_"
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8080
DEFAULT_DASHBOARD_URL = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/"
TAILSCALE_DASHBOARD_TARGET = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
DASHBOARD_STARTUP_TIMEOUT_SEC = 30
OPTIMIZER_SHUTDOWN_TIMEOUT_SEC = 10


def _configure_logging() -> None:
    configure_elapsed_logging()


def _optimizer_results_path() -> str:
    path = os.path.abspath(os.path.join(RESULTS_DIR, OPTIMIZER_RESULTS_SUBDIR))
    os.makedirs(path, exist_ok=True)
    return path


def _journal_path() -> str:
    return os.path.join(_optimizer_results_path(), OPTUNA_JOURNAL_FILE)


def _build_storage() -> optuna.storages.JournalStorage:
    """全 study で共有するローカル JournalStorage を返す"""
    journal_path = _journal_path()
    return optuna.storages.JournalStorage(
        JournalFileBackend(
            file_path=journal_path,
            lock_obj=JournalFileOpenLock(journal_path),
        )
    )


def _call_without_experimental_warning(
    factory: Callable[..., FactoryResult],
    *args: Any,
    **kwargs: Any,
) -> FactoryResult:
    """Optuna の試験的 API が出す警告を抑えて呼び出す"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        return factory(*args, **kwargs)


def _load_or_create_study(
    *,
    study_name: str,
    direction: str,
    storage: optuna.storages.BaseStorage,
    sampler: optuna.samplers.BaseSampler,
    pruner: Optional[optuna.pruners.BasePruner],
) -> optuna.Study:
    """既存 study を読み込み、存在しない場合だけ作成する"""
    try:
        return optuna.load_study(
            study_name=study_name,
            storage=storage,
            sampler=sampler,
            pruner=pruner,
        )
    except KeyError:
        try:
            return optuna.create_study(
                direction=direction,
                study_name=study_name,
                storage=storage,
                sampler=sampler,
                pruner=pruner,
            )
        except optuna.exceptions.DuplicatedStudyError:
            # 別のプロセスが同時に study を作成した場合は読み込み直す
            return optuna.load_study(
                study_name=study_name,
                storage=storage,
                sampler=sampler,
                pruner=pruner,
            )


def _set_trial_worker_attr(trial: optuna.trial.Trial) -> None:
    """強制終了後に孤立 trial を判定するためのワーカー情報を保存する"""
    trial.set_user_attr(
        "ahclib_worker",
        {"hostname": socket.gethostname(), "pid": os.getpid()},
    )


def _would_update_best(study: optuna.Study, value: float) -> bool:
    """途中推定値を COMPLETE にした場合に最良値を更新するか判定する"""
    try:
        best_value = study.best_value
    except ValueError:
        # WilcoxonPruner は比較対象がなければ通常は打ち切らない
        # 並列実行中の境界ケースでも公式例と同様に推定値を返す
        return False
    if study.direction == optuna.study.StudyDirection.MAXIMIZE:
        return value > best_value
    return value < best_value


def _is_process_alive(pid: int) -> bool:
    """同じ Linux ホスト上に PID が存在するか確認する"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        # 判定できない場合は実行中プロセスを誤って回収しないようにする
        return True
    return True


def _recover_orphaned_trials(study: optuna.Study) -> None:
    """終了済み ahclib ワーカーが残した RUNNING trial だけを FAIL へ戻す"""
    hostname = socket.gethostname()
    recovered_numbers: list[int] = []
    unknown_numbers: list[int] = []
    running_trials = study.get_trials(
        deepcopy=False,
        states=(optuna.trial.TrialState.RUNNING,),
    )
    for trial in running_trials:
        worker_info = trial.user_attrs.get("ahclib_worker")
        if not isinstance(worker_info, dict) or worker_info.get("hostname") != hostname:
            unknown_numbers.append(trial.number)
            continue
        try:
            pid = int(worker_info["pid"])
        except (KeyError, TypeError, ValueError):
            unknown_numbers.append(trial.number)
            continue
        if pid <= 0:
            unknown_numbers.append(trial.number)
            continue
        if _is_process_alive(pid):
            continue
        study.tell(
            trial.number,
            state=optuna.trial.TrialState.FAIL,
            skip_if_finished=True,
        )
        recovered_numbers.append(trial.number)

    if recovered_numbers:
        logger.warning(
            "Recovered orphaned RUNNING trials as FAIL: %s",
            ", ".join(map(str, recovered_numbers)),
        )
    if unknown_numbers:
        logger.warning(
            "RUNNING trials without verifiable ahclib worker metadata were left "
            "unchanged: %s",
            ", ".join(map(str, unknown_numbers)),
        )


def _migrate_legacy_postgres_studies(
    target_storage: optuna.storages.BaseStorage,
) -> None:
    """旧版の study 別 PostgreSQL database を共有 journal へコピーする"""
    try:
        import psycopg2
    except ImportError:
        logger.debug("psycopg2 is unavailable; skipping legacy study migration.")
        return

    try:
        connection = psycopg2.connect(dbname="postgres", connect_timeout=1)
    except psycopg2.Error:
        logger.debug("PostgreSQL is unavailable; skipping legacy study migration.")
        return

    try:
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT datname FROM pg_database WHERE left(datname, %s) = %s",
                    (len(LEGACY_POSTGRES_DB_PREFIX), LEGACY_POSTGRES_DB_PREFIX),
                )
                legacy_database_names = [row[0] for row in cursor.fetchall()]
        except psycopg2.Error:
            logger.debug(
                "Legacy PostgreSQL databases cannot be listed; skipping migration."
            )
            return
    finally:
        connection.close()

    existing_names = {
        summary.study_name
        for summary in optuna.get_all_study_summaries(storage=target_storage)
    }
    for database_name in legacy_database_names:
        legacy_url = f"postgresql+psycopg2:///{database_name}"
        try:
            summaries = optuna.get_all_study_summaries(storage=legacy_url)
        except Exception as error:
            logger.warning(f"Failed to read legacy Optuna DB {database_name}: {error}")
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
            except Exception as error:
                logger.warning(
                    f"Failed to migrate study {summary.study_name} "
                    f"from {database_name}: {error}"
                )
                continue
            existing_names.add(summary.study_name)
            logger.info(
                f"Migrated legacy study {summary.study_name} " f"from {database_name}."
            )


def _start_dashboard() -> subprocess.Popen[str]:
    journal_path = _journal_path()
    executable = shutil.which("optuna-dashboard")
    if executable is None:
        executable_suffix = ".exe" if os.name == "nt" else ""
        executable = os.path.join(
            os.path.dirname(sys.executable),
            f"optuna-dashboard{executable_suffix}",
        )
    logger.info("- dashboard     : starting ...")
    process = subprocess.Popen(
        # gunicorn のバックエンドは "Listening on" を出力しないため
        # WSL と Ubuntu で一貫して起動確認できる wsgiref を使う
        [
            executable,
            journal_path,
            "--server",
            "wsgiref",
            "--host",
            DASHBOARD_HOST,
            "--port",
            str(DASHBOARD_PORT),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stderr_lines: queue.Queue[Optional[str]] = queue.Queue()
    startup_finished = threading.Event()

    def _read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            # パイプは読み続けるが、起動確認後のリクエストログはキューへ入れない
            if not startup_finished.is_set():
                stderr_lines.put(line.rstrip())
        if not startup_finished.is_set():
            stderr_lines.put(None)

    threading.Thread(target=_read_stderr, daemon=True).start()
    try:
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
            recent_output = "\n".join(startup_messages) or "no error output"
            raise RuntimeError(f"Optuna Dashboard failed to start: {recent_output}")
        else:
            logger.warning(
                "Dashboard startup could not be confirmed within %s seconds; "
                "continuing with expected URL: %s",
                DASHBOARD_STARTUP_TIMEOUT_SEC,
                DEFAULT_DASHBOARD_URL,
            )
        return process
    except BaseException:
        _stop_dashboard(process)
        raise
    finally:
        startup_finished.set()


def _stop_optimizer_processes(
    optimizer_processes: list[multiprocessing.Process],
) -> None:
    """子プロセスの正常終了を待ち、残ったものだけを強制終了する"""
    # Process.start() が失敗した未起動プロセスには join() を呼べない
    started_processes = [
        process for process in optimizer_processes if process.pid is not None
    ]
    alive_processes = [process for process in started_processes if process.is_alive()]
    for optimizer_process in alive_processes:
        # 子側で SIGTERM を KeyboardInterrupt に変換し
        # Optuna が実行中 trial を FAIL に確定してから終了できるようにする
        optimizer_process.terminate()

    deadline = time.monotonic() + OPTIMIZER_SHUTDOWN_TIMEOUT_SEC
    for optimizer_process in alive_processes:
        optimizer_process.join(timeout=max(0.0, deadline - time.monotonic()))

    for optimizer_process in alive_processes:
        if optimizer_process.is_alive():
            logger.warning(
                "Force-killing optimizer session %s after %.0f seconds.",
                optimizer_process.name,
                OPTIMIZER_SHUTDOWN_TIMEOUT_SEC,
            )
            optimizer_process.kill()

    for optimizer_process in started_processes:
        optimizer_process.join()


def _stop_dashboard(process: subprocess.Popen[str]) -> None:
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


def _start_private_dashboard() -> TailscaleServe:
    logger.info("- remote access : starting Tailscale Serve ...")
    tailscale_serve = TailscaleServe.start(TAILSCALE_DASHBOARD_TARGET)
    logger.info(f"- private URL   : {to_bold(to_blue(tailscale_serve.private_url))}")
    logger.info("- access scope  : Tailscale tailnet only (not public)")
    return tailscale_serve


def run_optimizer_dashboard(tailscale: bool = False) -> None:
    """最適化を行わず、保存済みの全 study を Dashboard で表示する"""
    _configure_logging()
    storage = _build_storage()
    _migrate_legacy_postgres_studies(storage)
    logger.info("==============================================")
    logger.info(to_bold(to_blue("Optuna Dashboard")))
    logger.info(f"- storage       : {to_bold(_journal_path())}")
    _log_studies(storage)
    process = _start_dashboard()
    tailscale_serve: Optional[TailscaleServe] = None
    try:
        if tailscale:
            tailscale_serve = _start_private_dashboard()
        logger.info("==============================================")
        _wait_for_dashboard_close()
    finally:
        try:
            if tailscale_serve is not None:
                tailscale_serve.stop()
        finally:
            _stop_dashboard(process)


class Optimizer:
    def __init__(self, settings: AHCSettings) -> None:
        self.settings: AHCSettings = settings
        self.study_name = settings.study_name
        self.path = _optimizer_results_path()

    @staticmethod
    def _max_optuna_workers(requested: int) -> int:
        available_workers = max(1, multiprocessing.cpu_count() - 1)
        return max(1, min(requested, available_workers))

    @staticmethod
    def _split_trials(total_trials: int, worker_count: int) -> list[int]:
        """総 trial 数をワーカー間で均等に分配する"""
        quotient, remainder = divmod(total_trials, worker_count)
        return [
            quotient + (1 if worker_id < remainder else 0)
            for worker_id in range(worker_count)
            if quotient + (1 if worker_id < remainder else 0) > 0
        ]

    @staticmethod
    def _as_execute_args(args: Iterable[object]) -> tuple[object, ...]:
        return tuple(args)

    def optimize(
        self,
        sampler: Optional[str] = None,
        pruner: Optional[str] = None,
        tailscale: bool = False,
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
        start_time = time.time()

        def _objective(trial: optuna.trial.Trial) -> float:
            _set_trial_worker_attr(trial)
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            execute_args = self._as_execute_args(self.settings.objective(trial))
            trial.set_user_attr(
                "ahclib_execute_args",
                [str(argument) for argument in execute_args],
            )
            tester.append_execute_command(execute_args)
            scores = tester.run()
            trial.set_user_attr("ahclib_evaluated_cases", len(scores))
            trial.set_user_attr("ahclib_wilcoxon_stopped", False)
            return tester.get_score(scores)

        def _objective_wilcoxon_pruner(trial: optuna.trial.Trial) -> float:
            _set_trial_worker_attr(trial)
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            execute_args = self._as_execute_args(self.settings.objective(trial))
            trial.set_user_attr(
                "ahclib_execute_args",
                [str(argument) for argument in execute_args],
            )
            tester.append_execute_command(execute_args)
            pruning_result = tester.run_opt_pruner(trial)
            completed_scores = [
                score for score in pruning_result.scores if score is not None
            ]
            trial.set_user_attr(
                "ahclib_evaluated_cases",
                pruning_result.completed_count,
            )
            trial.set_user_attr(
                "ahclib_wilcoxon_stopped",
                pruning_result.pruned,
            )

            # 完了済みケースから推定値を返して途中評価の情報を sampler へ残す
            # 推定値が最良値を更新する場合だけ、未評価ケースを含む trial が
            # 最良にならないよう PRUNED にする
            score = tester.get_score(completed_scores)
            if pruning_result.pruned:
                count_width = len(str(len(pruning_result.scores)))
                logger.info(
                    to_green(
                        "wilcoxon stop | "
                        f"{str(pruning_result.completed_count).zfill(count_width)} / "
                        f"{len(pruning_result.scores)} | estimated score: {score}"
                    )
                )
                if _would_update_best(trial.study, score):
                    raise optuna.TrialPruned(
                        "Wilcoxon-stopped estimate would update the best value."
                    )
            return score

        storage = _build_storage()
        _migrate_legacy_postgres_studies(storage)
        objective_func: Callable[[optuna.trial.Trial], float] = _objective

        optuna_seed = self.settings.optuna_seed
        auto_sampler_class = None
        if sampler == "auto_sampler":
            auto_sampler_class = _call_without_experimental_warning(
                optunahub.load_module,
                "samplers/auto_sampler",
            ).AutoSampler
        else:
            sampler = "TPESampler"

        def _make_sampler(worker_id: int) -> optuna.samplers.BaseSampler:
            worker_seed = None if optuna_seed is None else optuna_seed + worker_id
            if auto_sampler_class is not None:
                return _call_without_experimental_warning(
                    auto_sampler_class,
                    seed=worker_seed,
                )
            return _call_without_experimental_warning(
                optuna.samplers.TPESampler,
                multivariate=True,
                n_startup_trials=self.settings.optuna_n_startup_trials,
                seed=worker_seed,
            )

        def _make_pruner() -> Optional[optuna.pruners.BasePruner]:
            if pruner == "WilcoxonPruner":
                return _call_without_experimental_warning(
                    optuna.pruners.WilcoxonPruner,
                    p_threshold=0.1,
                )
            return None

        logger.info(f"- sampler       : {to_bold(sampler)}")
        if pruner == "WilcoxonPruner":
            logger.info(f"- pruner        : {to_bold(pruner)}")
            objective_func = _objective_wilcoxon_pruner

        study = _load_or_create_study(
            study_name=self.settings.study_name,
            direction=self.settings.direction,
            storage=storage,
            sampler=_make_sampler(0),
            pruner=_make_pruner(),
        )
        _recover_orphaned_trials(study)

        initial_trial_count = len(study.trials)
        for initial_params in self.settings.optuna_init_trials:
            study.enqueue_trial(initial_params, skip_if_exists=True)

        worker_count = min(
            self._max_optuna_workers(self.settings.njobs_optuna),
            max(1, self.settings.n_trials),
        )
        trials_per_worker = self._split_trials(self.settings.n_trials, worker_count)
        logger.info(f"- opt sessions  : {to_bold(len(trials_per_worker))}")

        def _run_optimization_session(
            worker_id: int,
            session_trials: int,
            is_child_process: bool = False,
        ) -> None:
            if is_child_process:
                # Ctrl-C は親だけで受け、親からの SIGTERM を
                # KeyboardInterrupt として Optuna へ渡す
                # n_jobs=1 のため実行中 trial は FAIL へ正常に遷移する
                signal.signal(signal.SIGINT, signal.SIG_IGN)

                def _handle_terminate(_signum, _frame) -> None:
                    # Optuna は KeyboardInterrupt で trial を FAIL へ更新するが
                    # 既知の終了操作でもスタックトレースを WARNING 出力するため
                    # この子プロセス内だけ抑制する
                    optuna.logging.set_verbosity(optuna.logging.ERROR)
                    raise KeyboardInterrupt

                signal.signal(signal.SIGTERM, _handle_terminate)

            session_label = f"{worker_id + 1}/{len(trials_per_worker)}"
            try:
                session_study = optuna.load_study(
                    study_name=self.settings.study_name,
                    storage=_build_storage(),
                    sampler=_make_sampler(worker_id),
                    pruner=_make_pruner(),
                )
                logger.info(
                    "Optuna session %s started (%s trials).",
                    session_label,
                    session_trials,
                )
                session_study.optimize(
                    objective_func,
                    n_trials=session_trials,
                    timeout=optuna_timeout,
                    n_jobs=1,
                )
                logger.info("Optuna session %s finished.", session_label)
            except KeyboardInterrupt:
                logger.info("Optuna session %s interrupted.", session_label)
                if not is_child_process:
                    raise

        dashboard_process: Optional[subprocess.Popen[str]] = None
        tailscale_serve: Optional[TailscaleServe] = None
        optimizer_processes: list[multiprocessing.Process] = []
        try:
            logger.info("------------------------------------------")
            _log_studies(storage)

            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            tester.compile()

            if len(trials_per_worker) > 1:
                if "fork" not in multiprocessing.get_all_start_methods():
                    raise RuntimeError(
                        "Multi-session optimization requires the multiprocessing "
                        "'fork' start method."
                    )
                multiprocessing_context = multiprocessing.get_context("fork")
                optimizer_processes = [
                    multiprocessing_context.Process(
                        target=_run_optimization_session,
                        args=(worker_id, session_trials, True),
                        name=f"ahclib-opt-{worker_id}",
                    )
                    for worker_id, session_trials in enumerate(trials_per_worker)
                ]
                # Dashboard の標準エラー読取スレッドを作る前に fork する
                for optimizer_process in optimizer_processes:
                    optimizer_process.start()

            dashboard_process = _start_dashboard()
            if tailscale:
                tailscale_serve = _start_private_dashboard()
            logger.info("==============================================")

            if len(trials_per_worker) == 1:
                _run_optimization_session(0, trials_per_worker[0])
            else:
                for optimizer_process in optimizer_processes:
                    optimizer_process.join()
                failed_processes = [
                    optimizer_process
                    for optimizer_process in optimizer_processes
                    if optimizer_process.exitcode != 0
                ]
                if failed_processes:
                    failure_details = ", ".join(
                        f"{process.name} (exit={process.exitcode})"
                        for process in failed_processes
                    )
                    raise RuntimeError(f"Optimizer session failed: {failure_details}")

            # 子プロセスが追記した journal を新しい storage で読み直す
            study = optuna.load_study(
                study_name=self.settings.study_name,
                storage=_build_storage(),
                sampler=_make_sampler(0),
                pruner=_make_pruner(),
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
                    "elapsed_seconds": time.time() - start_time,
                    "sampler": sampler,
                    "pruner": pruner,
                    "requested_n_trials": self.settings.n_trials,
                    "trials_before_run": initial_trial_count,
                    "trials_after_run": len(study.trials),
                },
            )
            logger.info(
                f"Finish parameter searching. Time: "
                f"{time.time() - start_time:.2f}sec."
            )
            _wait_for_dashboard_close()

        except KeyboardInterrupt:
            logger.warning("Optimization interrupted; stopping all sessions ...")
            # トレースバックを表示せず、一般的な割り込み終了コードを返す
            raise SystemExit(130)
        except Exception:
            logger.exception("Optimizer failed.")
            raise
        finally:
            try:
                _stop_optimizer_processes(optimizer_processes)
            finally:
                try:
                    if tailscale_serve is not None:
                        tailscale_serve.stop()
                finally:
                    if dashboard_process is not None:
                        _stop_dashboard(dashboard_process)

    def _copy_snapshot(self, source: Optional[str], output_dir: str) -> None:
        if not source or not os.path.isfile(source):
            return
        destination = os.path.join(output_dir, os.path.basename(source))
        try:
            if os.path.exists(destination) and os.path.samefile(source, destination):
                return
            shutil.copy2(source, destination)
        except OSError as error:
            logger.warning(f"Failed to copy {source}: {error}")

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
                figure = plot_func(study)
                figure.write_html(os.path.join(img_path, f"{filename}.html"))
                try:
                    figure.write_image(os.path.join(img_path, f"{filename}.png"))
                except (ValueError, RuntimeError, OSError) as error:
                    logger.debug(f"Failed to write {filename}.png: {error}")
            except (ValueError, RuntimeError) as error:
                logger.warning(f"Failed to create {filename} plot: {error}")

    def output_study(
        self,
        study: optuna.Study,
        run_info: Optional[dict[str, Any]] = None,
    ) -> None:
        study_path = os.path.join(self.path, self.study_name)
        os.makedirs(study_path, exist_ok=True)
        run_metadata = dict(run_info or {})
        run_id = None
        if run_info is not None:
            run_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            run_metadata["run_id"] = run_id

        try:
            best_trial = study.best_trial
        except ValueError:
            best_trial = None

        with open(
            os.path.join(study_path, "result.txt"),
            "w",
            encoding="utf-8",
        ) as result_file:
            if best_trial is None:
                print("No completed trials.", file=result_file)
            else:
                print(best_trial, file=result_file)

        study.trials_dataframe().to_csv(
            os.path.join(study_path, "trials.csv"), index=False
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
        with open(
            os.path.join(study_path, "study.json"),
            "w",
            encoding="utf-8",
        ) as summary_file:
            json.dump(
                summary,
                summary_file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        self._copy_snapshot(self.settings.filename, study_path)
        try:
            settings_source = inspect.getsourcefile(self.settings)
        except TypeError:
            settings_source = None
        self._copy_snapshot(settings_source, study_path)

        # study 直下を最新状態に更新し、各実行時点の trial 一覧と
        # メタデータとソースを実行日時別のディレクトリにも保存する
        if run_id is not None:
            run_path = os.path.join(study_path, "runs", run_id)
            os.makedirs(run_path, exist_ok=False)
            for filename in ("result.txt", "trials.csv", "study.json"):
                shutil.copy2(os.path.join(study_path, filename), run_path)
            self._copy_snapshot(self.settings.filename, run_path)
            self._copy_snapshot(settings_source, run_path)

        image_path = os.path.join(study_path, "images")
        os.makedirs(image_path, exist_ok=True)
        self._output_plots(study, image_path)


def run_optimizer(
    settings: AHCSettings,
    sampler: Optional[str] = None,
    pruner: Optional[str] = None,
    tailscale: bool = False,
) -> None:
    _configure_logging()
    optimizer = Optimizer(settings)
    try:
        optimizer.optimize(sampler, pruner, tailscale=tailscale)
    except KeyboardInterrupt:
        # storage 初期化中など Optimizer 内部の try より前の割り込みも
        # トレースバックなしで終了させる
        logger.warning("Optimization interrupted.")
        raise SystemExit(130)


if __name__ == "__main__":
    run_optimizer(AHCSettings)
