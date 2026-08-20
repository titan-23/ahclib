import argparse
import collections
import concurrent.futures
import contextlib
import csv
import datetime
import math
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from logging import getLogger
from random import Random
from typing import (
    Any,
    Callable,
    ClassVar,
    ContextManager,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    Optional,
    Union,
)

import optuna
import pandas as pd

from .ahc_settings import AHCSettings
from .ahc_util import to_blue, to_bold, to_green, to_red
from .logging_util import configure_elapsed_logging

logger = getLogger(__name__)

MS_PER_SEC = 1000

# ``score = X`` を大文字小文字や空白の違いを無視して取得する
SCORE_PATTERN = re.compile(r"score\s*=\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)

RESULTS_DIR = "ahclib_results"
ALL_TESTS_SUBDIR = "all_tests"
RESULT_CSV = "result.csv"
ERR_SUBDIR = "err"
OUT_SUBDIR = "out"
LOCAL_OUT_DIR = "./out/"
SETTINGS_FILE = "ahc_settings.py"
RESULT_DIR_DATETIME_FORMAT = "%Y_%m_%d_%H_%M_%S"

CSV_HEADERS_REL = ["filename", "score", "rel_score", "state", "time"]
CSV_HEADERS_NOREL = ["filename", "score", "state", "time"]

SolverState = Literal["AC", "TLE", "ERROR", "INNER_ERROR"]
Direction = Literal["minimize", "maximize"]
Score = Union[int, float]
CaseResult = tuple[str, Score, float, SolverState, str]
CpuLock = ContextManager[Any]

# 打ち切り判定後にソルバーを終了するための監視間隔と猶予時間
PRUNER_CANCEL_POLL_SEC = 0.05
PROCESS_TERMINATE_GRACE_SEC = 0.5

# 主な処理は外部ソルバーの待機なので、GIL の影響が小さい ThreadPoolExecutor を使う
# ProcessPoolExecutor では集計状態の共有と関数の直列化が必要になる


def get_cpu_affinity_ids(njobs: int) -> tuple[int, ...]:
    """solver に割り当てる logical CPU の一覧を返す"""
    get_affinity = getattr(os, "sched_getaffinity", None)
    if os.name != "posix" or get_affinity is None:
        raise RuntimeError("--cpu-affinity は Linux 環境でのみ利用できます")
    if shutil.which("taskset") is None:
        raise RuntimeError("--cpu-affinity には taskset が必要です (Ubuntu では util-linux に含まれます)")

    available_cpu_ids = tuple(sorted(get_affinity(0)))
    if not available_cpu_ids:
        raise RuntimeError("利用可能な logical CPU が見つかりません")

    # 複数 CPU がある場合は最小 ID を solver 用から外す
    solver_cpu_ids = available_cpu_ids[1:] if len(available_cpu_ids) > 1 else available_cpu_ids
    return solver_cpu_ids[: max(1, njobs)]


def _command_with_cpu_affinity(command: list[str], cpu_id: Optional[int]) -> list[str]:
    if cpu_id is None:
        return command
    return ["taskset", "--cpu-list", str(cpu_id), *command]


def _cpu_lock_context(cpu_lock: Optional[CpuLock]) -> ContextManager[Any]:
    return cpu_lock if cpu_lock is not None else contextlib.nullcontext()


@dataclass
class WorkerState:
    """ワーカー間で共有し、ロックを取得して更新する集計値"""

    lock: threading.Lock = field(default_factory=threading.Lock)
    counter: int = 0
    score_sum: float = 0.0
    valid_cnt: int = 0
    rel_log_sum: float = 0.0
    rel_cnt: int = 0
    rel_good_cnt: int = 0
    rel_same_cnt: int = 0
    rel_bad_cnt: int = 0


@dataclass(frozen=True)
class PrunerRunResult:
    """Optuna の打ち切り判定を伴う実行結果"""

    scores: list[Optional[float]]
    pruned: bool

    @property
    def completed_count(self) -> int:
        return sum(score is not None for score in self.scores)


def _decode_process_output(output: Union[str, bytes, None]) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return output.decode("utf-8", errors="ignore")


def _extract_last_score(stderr: str, is_int: bool) -> Score:
    """stderr を後ろから走査し、最後に現れる `score = X` の X を返す"""
    for line in reversed(stderr.splitlines()):
        matches = SCORE_PATTERN.findall(line)
        if matches:
            score_str = matches[-1]
            return int(score_str) if is_int else float(score_str)
    raise ValueError("`score = X` が標準エラー出力に見つかりません")


def _execute_solver(
    input_file: str,
    command: list[str],
    timeout: Optional[float],
    is_int: bool,
    cpu_id: Optional[int] = None,
    cpu_lock: Optional[CpuLock] = None,
) -> tuple[SolverState, Score, str, str, float]:
    """入力ファイルをソルバーへ渡し、状態・スコア・出力・実行時間を返す"""
    with open(input_file, "r", encoding="utf-8") as input_stream:
        input_text = input_stream.read()
    try:
        with _cpu_lock_context(cpu_lock):
            start = time.perf_counter()
            result = subprocess.run(
                _command_with_cpu_affinity(command, cpu_id),
                input=input_text,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=True,
            )
            elapsed = time.perf_counter() - start
        score = _extract_last_score(result.stderr, is_int)
        return "AC", score, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired as e:
        elapsed = timeout if timeout is not None else -1.0
        return (
            "TLE",
            math.nan,
            _decode_process_output(e.stdout),
            _decode_process_output(e.stderr),
            elapsed,
        )
    except subprocess.CalledProcessError as e:
        return "ERROR", math.nan, e.stdout or "", e.stderr or "", -1.0
    except Exception as e:
        logger.exception(e)
        return "INNER_ERROR", math.nan, "", "", -1.0


def _terminate_process(
    process: subprocess.Popen[str],
) -> tuple[str, str]:
    """ソルバーとその子プロセスを終了し、残っている標準出力・標準エラーを返す"""
    if process.poll() is None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except OSError:
            pass

    try:
        stdout, stderr = process.communicate(timeout=PROCESS_TERMINATE_GRACE_SEC)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


def _execute_solver_cancellable(
    input_file: str,
    command: list[str],
    timeout: Optional[float],
    is_int: bool,
    cancel_event: threading.Event,
    cpu_id: Optional[int] = None,
    cpu_lock: Optional[CpuLock] = None,
) -> Optional[tuple[SolverState, Score, str, str, float]]:
    """ソルバーを実行し、中止通知を受けた場合は終了して ``None`` を返す"""
    if cancel_event.is_set():
        return None

    with open(input_file, "r", encoding="utf-8") as input_stream:
        input_text = input_stream.read()

    process: Optional[subprocess.Popen[str]] = None
    try:
        with _cpu_lock_context(cpu_lock):
            if cancel_event.is_set():
                return None
            start = time.perf_counter()
            process = subprocess.Popen(
                _command_with_cpu_affinity(command, cpu_id),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=(os.name == "posix"),
            )
            communicate_input: Optional[str] = input_text

            while True:
                if cancel_event.is_set():
                    _terminate_process(process)
                    return None

                elapsed = time.perf_counter() - start
                remaining = None if timeout is None else timeout - elapsed
                if remaining is not None and remaining <= 0:
                    stdout, stderr = _terminate_process(process)
                    return "TLE", math.nan, stdout, stderr, timeout

                wait_sec = PRUNER_CANCEL_POLL_SEC
                if remaining is not None:
                    wait_sec = min(wait_sec, remaining)

                try:
                    stdout, stderr = process.communicate(
                        input=communicate_input,
                        timeout=wait_sec,
                    )
                except subprocess.TimeoutExpired:
                    # 最初の communicate が input を保持するため再送しない
                    communicate_input = None
                    continue

                elapsed = time.perf_counter() - start
                if process.returncode != 0:
                    return "ERROR", math.nan, stdout or "", stderr or "", -1.0
                score = _extract_last_score(stderr or "", is_int)
                return "AC", score, stdout or "", stderr or "", elapsed
    except Exception as e:
        if process is not None and process.poll() is None:
            _terminate_process(process)
        logger.exception(e)
        return "INNER_ERROR", math.nan, "", "", -1.0


def _calculate_relative_score(
    score: Score,
    input_file: str,
    baseline_scores: dict[str, float],
) -> float:
    """基準結果に対する比を返し、基準値がなければ ``-1.0`` を返す"""
    if input_file not in baseline_scores:
        return -1.0
    return score / baseline_scores[input_file]


def _format_relative_score(
    relative_score: float,
    direction: Direction,
    fmt: str = ".4f",
) -> str:
    """相対スコアを最適化方向に応じて色付けする"""
    if math.isnan(relative_score):
        return to_red("nan")
    if relative_score == -1:
        return to_red(f"{relative_score:{fmt}}")
    formatted_score = f"{relative_score:{fmt}}"
    if relative_score == 1.0:
        return formatted_score
    is_improved = relative_score < 1.0 if direction == "minimize" else relative_score > 1.0
    return to_green(formatted_score) if is_improved else to_red(formatted_score)


def _format_count(count: int, is_good: bool) -> str:
    """改善件数を緑、悪化件数を赤で表示する"""
    return to_green(count) if is_good else to_red(count)


def _log_solver_error(input_file: str, state: SolverState) -> None:
    """AC 以外の終了状態をログへ出力する"""
    if state == "TLE":
        logger.error(to_red(f"TLE occured in {input_file}"))
    elif state == "ERROR":
        logger.error(to_red(f"Error occured in {input_file}"))
    elif state == "INNER_ERROR":
        logger.error(to_red(f"!!! Error occured in {input_file}"))


def _write_record(output_dir: str, filename: str, stdout: str, stderr: str) -> None:
    """ソルバーの標準出力と標準エラー出力を保存する"""
    with open(os.path.join(output_dir, ERR_SUBDIR, filename), "w", encoding="utf-8") as error_file:
        error_file.write(stderr)
    with open(os.path.join(output_dir, OUT_SUBDIR, filename), "w", encoding="utf-8") as output_file:
        output_file.write(stdout)


@dataclass
class _LogFormatter:
    """ケースごとの実行ログを整形する"""

    SCORE_WIDTH: ClassVar[int] = 10
    TIME_WIDTH: ClassVar[int] = 11

    direction: Direction
    use_relative_score: bool
    total_files: int
    is_int: bool

    def _count_width(self) -> int:
        return len(str(self.total_files))

    def format_score(self, score: Score) -> str:
        return f"{score:>{self.SCORE_WIDTH}}" if self.is_int else f"{score:>{self.SCORE_WIDTH}.3f}"

    def format_average_score(self, average: float) -> str:
        return f"{average:>{self.SCORE_WIDTH}.3f}"

    def format_time(self, elapsed: float) -> str:
        return f"{f'{elapsed:.3f} sec':>{self.TIME_WIDTH}}"

    def format_tle_time(self, timeout: float) -> str:
        return f"{f'>{timeout:.3f} sec':>{self.TIME_WIDTH}}"

    def format_count(self, count: int) -> str:
        return f"{count:>{self._count_width()}}"

    def format_relative_counts(
        self,
        improved: int,
        unchanged: int,
        worsened: int,
    ) -> str:
        width = self._count_width()
        improved_text = f"{improved:>{width}}"
        unchanged_text = f"{unchanged:>{width}}"
        worsened_text = f"{worsened:>{width}}"
        return f"{to_green(improved_text)} / {unchanged_text} / " f"{to_red(worsened_text)}"

    def format_relative_score(
        self,
        relative_score: float,
        fmt: str = ".4f",
    ) -> str:
        return _format_relative_score(relative_score, self.direction, fmt)

    def build_ac_line(
        self,
        count: int,
        input_file: str,
        score: Score,
        elapsed: float,
        relative_score: float,
        average_score: float,
        relative_average_text: str,
        relative_count_text: str,
    ) -> str:
        parts = [
            f"{self.format_count(count)} / {self.total_files}",
            input_file,
            self.format_score(score),
            self.format_time(elapsed),
        ]
        if self.use_relative_score:
            parts.extend(
                [
                    self.format_relative_score(relative_score, fmt=".3f"),
                    f"Ave: {self.format_average_score(average_score)}",
                    f"RelAve: {relative_average_text}",
                    f"Better/Same/Worse: {relative_count_text}",
                ]
            )
        else:
            parts.append(f"Ave: {self.format_average_score(average_score)}")
        return f"| {' | '.join(parts)} |"

    def build_tle_line(self, count: int, input_file: str, timeout: float) -> str:
        score_text = "-" * self.SCORE_WIDTH
        time_text = self.format_tle_time(timeout)
        return (
            f"| {self.format_count(count)} / {self.total_files} | "
            f"{input_file} | {score_text} | {to_red(time_text)} |"
        )


@dataclass
class _RunConfig:
    """全ケースに共通する実行設定で、生成後は変更しない"""

    command: list[str]
    timeout: Optional[float]
    use_relative_score: bool
    baseline_scores: dict[str, float]
    verbose: bool
    direction: Direction
    output_dir: str
    record: bool
    is_int: bool
    formatter: _LogFormatter


def _run_case_for_opt(
    input_file: str,
    command: list[str],
    timeout: Optional[float],
    is_int: bool,
    use_relative_score: bool,
    baseline_scores: dict[str, float],
    cancel_event: Optional[threading.Event] = None,
    cpu_id: Optional[int] = None,
    cpu_lock: Optional[CpuLock] = None,
) -> Optional[float]:
    """Optuna 用に 1 ケースを実行し、失敗時は nan を返す"""
    if cancel_event is None:
        result = _execute_solver(input_file, command, timeout, is_int, cpu_id, cpu_lock)
    else:
        result = _execute_solver_cancellable(
            input_file,
            command,
            timeout,
            is_int,
            cancel_event,
            cpu_id,
            cpu_lock,
        )
        if result is None:
            return None

    state, score, _, _, _ = result
    if state != "AC":
        _log_solver_error(input_file, state)
        return math.nan
    if use_relative_score:
        return _calculate_relative_score(score, input_file, baseline_scores)
    return score


def _worker_process_file_opt_pruner(args) -> tuple[int, Optional[float]]:
    (
        input_file,
        case_index,
        command,
        timeout,
        is_int,
        use_relative_score,
        baseline_scores,
        cancel_event,
        cpu_id,
        cpu_lock,
    ) = args
    score = _run_case_for_opt(
        input_file,
        command,
        timeout,
        is_int,
        use_relative_score,
        baseline_scores,
        cancel_event,
        cpu_id,
        cpu_lock,
    )
    return case_index, score


def _worker_process_file_light(args) -> float:
    """記録を残さずに 1 ケースを実行する"""
    (
        input_file,
        command,
        timeout,
        is_int,
        use_relative_score,
        baseline_scores,
        cancel_event,
        cpu_id,
        cpu_lock,
    ) = args
    score = _run_case_for_opt(
        input_file,
        command,
        timeout,
        is_int,
        use_relative_score,
        baseline_scores,
        cancel_event,
        cpu_id,
        cpu_lock,
    )
    return math.nan if score is None else score


def _increment_counter(state: WorkerState) -> int:
    """ロック中に完了件数を 1 増やし、新しい値を返す"""
    with state.lock:
        state.counter += 1
        return state.counter


def _update_running_stats(
    state: WorkerState,
    formatter: _LogFormatter,
    score: Score,
    relative_score: float,
) -> tuple[int, float, str, str]:
    """ロック中に集計値を更新し、表示に必要な値を返す"""
    with state.lock:
        state.counter += 1
        count = state.counter
        if not math.isnan(score):
            state.score_sum += score
            state.valid_cnt += 1
        valid_count = state.valid_cnt
        average_score = state.score_sum / valid_count if valid_count > 0 else 0.0

        relative_average_text = ""
        relative_count_text = ""
        if formatter.use_relative_score:
            if not math.isnan(relative_score) and relative_score != -1:
                state.rel_log_sum += math.log(relative_score)
                state.rel_cnt += 1
                if relative_score == 1.0:
                    state.rel_same_cnt += 1
                else:
                    is_good = (relative_score < 1.0) if formatter.direction == "minimize" else (relative_score > 1.0)
                    if is_good:
                        state.rel_good_cnt += 1
                    else:
                        state.rel_bad_cnt += 1
            relative_count_text = formatter.format_relative_counts(
                state.rel_good_cnt, state.rel_same_cnt, state.rel_bad_cnt
            )
            if state.rel_cnt > 0:
                average_relative_score = math.exp(state.rel_log_sum / state.rel_cnt)
                relative_average_text = formatter.format_relative_score(average_relative_score)
            else:
                relative_average_text = to_red("nan")
    return (
        count,
        average_score,
        relative_average_text,
        relative_count_text,
    )


def _handle_ac_case(
    input_file: str,
    score: Score,
    stdout: str,
    stderr: str,
    elapsed: float,
    config: _RunConfig,
    state: WorkerState,
) -> CaseResult:
    relative_score = _calculate_relative_score(score, input_file, config.baseline_scores)
    if config.verbose:
        (
            count,
            average_score,
            relative_average_text,
            relative_count_text,
        ) = _update_running_stats(state, config.formatter, score, relative_score)
        logger.info(
            config.formatter.build_ac_line(
                count,
                input_file,
                score,
                elapsed,
                relative_score,
                average_score,
                relative_average_text,
                relative_count_text,
            )
        )
    if config.record:
        _write_record(
            config.output_dir,
            os.path.basename(input_file),
            stdout,
            stderr,
        )
    return input_file, score, relative_score, "AC", f"{elapsed:.3f}"


def _handle_tle_case(
    input_file: str,
    stdout: str,
    stderr: str,
    config: _RunConfig,
    state: WorkerState,
) -> CaseResult:
    count = _increment_counter(state)
    if config.verbose:
        logger.info(config.formatter.build_tle_line(count, input_file, config.timeout))
    if config.record:
        _write_record(
            config.output_dir,
            os.path.basename(input_file),
            stdout,
            stderr,
        )
    return input_file, math.nan, math.nan, "TLE", f"{config.timeout:.3f}"


def _handle_error_case(
    input_file: str,
    solver_state: SolverState,
    stdout: str,
    stderr: str,
    config: _RunConfig,
    state: WorkerState,
) -> CaseResult:
    _increment_counter(state)
    if solver_state == "ERROR" and config.record:
        _write_record(
            config.output_dir,
            os.path.basename(input_file),
            stdout,
            stderr,
        )
    _log_solver_error(input_file, solver_state)
    return input_file, math.nan, math.nan, solver_state, "-1"


def _worker_process_file(args) -> CaseResult:
    """1 ケースを実行し、ログとファイル出力を処理する"""
    input_file, config, state, cpu_id, cpu_lock = args
    solver_state, score, stdout, stderr, elapsed = _execute_solver(
        input_file,
        config.command,
        config.timeout,
        config.is_int,
        cpu_id,
        cpu_lock,
    )
    if solver_state == "AC":
        return _handle_ac_case(
            input_file,
            score,
            stdout,
            stderr,
            elapsed,
            config,
            state,
        )
    if solver_state == "TLE":
        return _handle_tle_case(input_file, stdout, stderr, config, state)
    return _handle_error_case(
        input_file,
        solver_state,
        stdout,
        stderr,
        config,
        state,
    )


def _submit_next(
    executor: concurrent.futures.Executor,
    argument_iterator: Iterator,
    pending_futures: dict,
    worker: Callable,
    lane_id: Optional[int] = None,
) -> None:
    """次の引数を executor へ渡し、入力が尽きていれば何もしない"""
    try:
        worker_arguments = next(argument_iterator)
    except StopIteration:
        return
    pending_futures[executor.submit(worker, worker_arguments)] = lane_id


class ParallelTester:
    def __init__(
        self,
        direction: Direction,
        filename: str,
        compile_command: Optional[str],
        execute_command: str,
        input_file_names: list[str],
        cpu_count: int,
        verbose: bool,
        get_score: Callable[[list[Optional[float]]], float],
        timeout: Optional[float],
        use_relative_score: bool,
        pre_dir_name: str,
        is_int: bool = True,
        optuna_seed: Optional[int] = None,
        cpu_ids: tuple[int, ...] = (),
        cpu_locks: Optional[Mapping[int, CpuLock]] = None,
    ) -> None:
        """ParallelTester を初期化する

        Args:
            direction: ``minimize`` または ``maximize``
            compile_command: コンパイルコマンドで ``None`` なら実行しない
            execute_command: ソルバーの実行コマンド
            input_file_names: 入力ファイル名のリスト
            cpu_count: 並列ワーカ数
            verbose: ケースごとのログを表示するか
            get_score: ケース別スコアを集約する関数
            timeout: 1 ケースの制限時間で単位は ms、``None`` なら無制限
            is_int: 整数スコアなら ``True``、小数スコアなら ``False``
            optuna_seed: ``run_opt_pruner`` の入力順を決める乱数初期値
            cpu_ids: solver を固定する logical CPU の一覧で、空なら固定しない
            cpu_locks: Optuna session 間で共有する CPU ごとの lock
        """
        if direction != "minimize" and direction != "maximize":
            logger.critical(f"direction must be `minimize` or `maximize` but got {direction}.")
            raise ValueError(f"Invalid direction: {direction}")

        self.direction = direction
        self.filename = filename
        self.compile_command = compile_command.split() if compile_command else None
        self.execute_command = execute_command.split()
        self.added_command: list[str] = []
        self.input_file_names = input_file_names
        self.cpu_count = cpu_count
        self.cpu_ids = cpu_ids
        self.cpu_locks = dict(cpu_locks or {})
        self.verbose = verbose
        self.get_score = get_score
        self.timeout = timeout / MS_PER_SEC if (timeout is not None) and (timeout >= 0) else None
        self.use_relative_score = use_relative_score
        self.is_int = is_int
        pre_csv = os.path.join(RESULTS_DIR, ALL_TESTS_SUBDIR, pre_dir_name, RESULT_CSV)
        self.pre_data: dict[str, float] = {}
        if os.path.exists(pre_csv):
            df = pd.read_csv(pre_csv)
            self.pre_data = dict(zip(df["filename"], df["score"]))

        # trial ごとに異なる再現可能な入力順を作るための乱数初期値
        self.optuna_seed = optuna_seed
        self.last_output_dir: Optional[str] = None

    def _cpu_target(self, case_index: int) -> tuple[Optional[int], Optional[CpuLock]]:
        if not self.cpu_ids:
            return None, None
        cpu_id = self.cpu_ids[case_index % len(self.cpu_ids)]
        return cpu_id, self.cpu_locks.get(cpu_id)

    def _prepare_worker_arguments(self, case_index: int, worker_arguments: tuple[Any, ...]) -> tuple[Any, ...]:
        cpu_id, cpu_lock = self._cpu_target(case_index)
        return (*worker_arguments, cpu_id, cpu_lock)

    def show_score(self, scores: list[float]) -> float:
        """ケース別スコアを集約してログへ出力する"""
        score = self.get_score(scores)
        logger.info(f"Ave.{score}")
        return score

    def append_execute_command(self, args: Iterable[object]) -> None:
        """ソルバーへ渡すコマンドライン引数を追加する"""
        for arg in args:
            self.added_command.append(str(arg))

    def clear_execute_command(self) -> None:
        """これまでに追加したコマンドライン引数を削除する"""
        self.added_command.clear()

    def compile(self) -> None:
        """設定されたコマンドでコンパイルし、失敗時は終了する"""
        if self.compile_command is None:
            return
        try:
            subprocess.run(
                self.compile_command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            logger.error(to_red("Compile failed"))
            if error.stderr:
                logger.error(error.stderr.rstrip())
            sys.exit(1)

    def _map_in_parallel(
        self,
        worker: Callable[[Any], Any],
        worker_arguments: list[tuple[Any, ...]],
        cancel_event: Optional[threading.Event] = None,
    ) -> list[Any]:
        """ThreadPoolExecutor で全ケースを並列実行する"""
        max_workers = max(1, self.cpu_count)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        try:
            prepared_arguments = [
                self._prepare_worker_arguments(case_index, arguments)
                for case_index, arguments in enumerate(worker_arguments)
            ]
            if not self.cpu_ids:
                return list(executor.map(worker, prepared_arguments))

            lanes: list[list[tuple[int, tuple[Any, ...]]]] = [[] for _ in self.cpu_ids]
            for case_index, arguments in enumerate(prepared_arguments):
                lanes[case_index % len(lanes)].append((case_index, arguments))

            def run_lane(
                lane: list[tuple[int, tuple[Any, ...]]],
            ) -> list[tuple[int, Any]]:
                return [(case_index, worker(arguments)) for case_index, arguments in lane]

            lane_results = list(executor.map(run_lane, lanes))
            indexed_results = [indexed_result for lane_result in lane_results for indexed_result in lane_result]
            indexed_results.sort(key=lambda result: result[0])
            return [result for _, result in indexed_results]
        finally:
            # KeyboardInterrupt 時は executor の終了待ちより先にソルバーへ通知する
            if cancel_event is not None:
                cancel_event.set()
            executor.shutdown(wait=True, cancel_futures=True)

    def run_opt_pruner(self, trial: optuna.trial.Trial) -> PrunerRunResult:
        """Optuna trial を並列評価し、pruner の判定に従って打ち切る

        Returns:
            ケース別スコアと打ち切りの有無で、未完了ケースは ``None``
        """
        scores: list[Optional[float]] = [None] * len(self.input_file_names)
        indexed_input_files = list(enumerate(self.input_file_names))
        shuffle_seed = None if self.optuna_seed is None else self.optuna_seed + trial.number
        Random(shuffle_seed).shuffle(indexed_input_files)
        cancel_event = threading.Event()

        command = self.execute_command + self.added_command
        scheduled_arguments = []
        for case_index, input_file in indexed_input_files:
            arguments = (
                input_file,
                case_index,
                command,
                self.timeout,
                self.is_int,
                self.use_relative_score,
                self.pre_data,
                cancel_event,
            )
            cpu_id, _ = self._cpu_target(case_index)
            scheduled_arguments.append((cpu_id, self._prepare_worker_arguments(case_index, arguments)))

        max_workers = max(1, self.cpu_count)
        argument_iterator = iter(arguments for _, arguments in scheduled_arguments)
        lane_iterators: dict[int, Iterator] = {}
        if self.cpu_ids:
            lane_arguments: dict[int, list[tuple[Any, ...]]] = {cpu_id: [] for cpu_id in self.cpu_ids}
            for cpu_id, arguments in scheduled_arguments:
                if cpu_id is not None:
                    lane_arguments[cpu_id].append(arguments)
            lane_iterators = {cpu_id: iter(arguments) for cpu_id, arguments in lane_arguments.items()}
        pruned = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            pending_futures: dict[concurrent.futures.Future, Optional[int]] = {}
            try:
                if self.cpu_ids:
                    for cpu_id, lane_iterator in lane_iterators.items():
                        _submit_next(
                            executor,
                            lane_iterator,
                            pending_futures,
                            _worker_process_file_opt_pruner,
                            cpu_id,
                        )
                else:
                    for _ in range(max_workers):
                        _submit_next(
                            executor,
                            argument_iterator,
                            pending_futures,
                            _worker_process_file_opt_pruner,
                        )

                while pending_futures:
                    done, _ = concurrent.futures.wait(
                        pending_futures,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for future in done:
                        lane_id = pending_futures.pop(future)
                        case_index, score = future.result()
                        if score is None:
                            continue
                        trial.report(score, case_index)
                        scores[case_index] = score
                        if trial.should_prune():
                            pruned = True
                            # Future.cancel() では実行中のソルバーを停止できないため
                            # 終了通知を介して各ワーカーから子プロセスを終了する
                            cancel_event.set()
                            for pending in pending_futures:
                                pending.cancel()
                            break
                        if lane_id is None:
                            _submit_next(
                                executor,
                                argument_iterator,
                                pending_futures,
                                _worker_process_file_opt_pruner,
                            )
                        else:
                            _submit_next(
                                executor,
                                lane_iterators[lane_id],
                                pending_futures,
                                _worker_process_file_opt_pruner,
                                lane_id,
                            )
                    if pruned:
                        break
            finally:
                # Ctrl-C でも with 節の終了待ちに入る前にソルバーを終了する
                cancel_event.set()
                for pending in pending_futures:
                    pending.cancel()
        return PrunerRunResult(scores=scores, pruned=pruned)

    def run(self) -> list[float]:
        """全ケースを並列実行し、スコアだけを返す"""
        cancel_event = threading.Event()
        command = self.execute_command + self.added_command
        worker_arguments = [
            (
                input_file,
                command,
                self.timeout,
                self.is_int,
                self.use_relative_score,
                self.pre_data,
                cancel_event,
            )
            for input_file in self.input_file_names
        ]
        return self._map_in_parallel(
            _worker_process_file_light,
            worker_arguments,
            cancel_event=cancel_event,
        )

    def _create_output_dir(self) -> str:
        """実行日時を名前に含む出力ディレクトリを作る"""
        created_at = datetime.datetime.now()
        output_dir = os.path.join(
            RESULTS_DIR,
            ALL_TESTS_SUBDIR,
            created_at.strftime(RESULT_DIR_DATETIME_FORMAT),
        )
        if os.path.exists(output_dir):
            logger.error(to_red(f"Output dir already exists (aborting to avoid overwrite): {output_dir}"))
            raise FileExistsError(output_dir)
        os.makedirs(output_dir)
        return output_dir

    def _copy_source_files(self, output_dir: str) -> None:
        """main ファイルと `ahc_settings.py` を `output_dir` 配下にコピーする"""
        src_basename = os.path.basename(self.filename)
        try:
            shutil.copy2(self.filename, os.path.join(output_dir, src_basename))
        except Exception as error:
            logger.warning(f"Failed to copy source file {self.filename}: {error}")
        try:
            shutil.copy2(SETTINGS_FILE, os.path.join(output_dir, SETTINGS_FILE))
        except Exception as error:
            logger.warning(f"Failed to copy {SETTINGS_FILE}: {error}")

    def _ensure_record_subdirs(self, output_dir: str) -> None:
        """err/ out/ サブディレクトリを作る"""
        os.makedirs(os.path.join(output_dir, ERR_SUBDIR), exist_ok=True)
        os.makedirs(os.path.join(output_dir, OUT_SUBDIR), exist_ok=True)

    def _setup_output_dir(self, record: bool) -> str:
        """出力ディレクトリを用意しソースをコピーする"""
        output_dir = self._create_output_dir()
        self._copy_source_files(output_dir)
        if record:
            self._ensure_record_subdirs(output_dir)
        return output_dir

    def _write_result_csv(
        self,
        output_dir: str,
        results: list[CaseResult],
    ) -> None:
        """`{output_dir}/result.csv` へ書き出す"""
        csv_path = os.path.join(output_dir, RESULT_CSV)
        with open(csv_path, "w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            if self.use_relative_score:
                writer.writerow(CSV_HEADERS_REL)
                for filename, score, relative_score, state, elapsed in results:
                    writer.writerow([filename, score, relative_score, state, elapsed])
            else:
                writer.writerow(CSV_HEADERS_NOREL)
                for filename, score, _, state, elapsed in results:
                    writer.writerow([filename, score, state, elapsed])

    def _copy_outputs_to_local(self, output_dir: str) -> None:
        """`{output_dir}/out/` の中身を `./out/` にコピーする"""
        if not os.path.exists(LOCAL_OUT_DIR):
            os.makedirs(LOCAL_OUT_DIR)
        source_directory = os.path.join(output_dir, OUT_SUBDIR)
        for item in os.listdir(source_directory):
            source_path = os.path.join(source_directory, item)
            destination_path = os.path.join(LOCAL_OUT_DIR, item)
            if os.path.isfile(source_path):
                shutil.copy2(source_path, destination_path)
            elif os.path.isdir(source_path):
                shutil.copytree(source_path, destination_path)

    def run_record(self, record: bool, memo: Optional[str] = None) -> list[CaseResult]:
        """全ケースを並列実行し CSV と (record=True なら) 入出力ファイルも保存する"""
        output_dir = self._setup_output_dir(record)
        self.last_output_dir = output_dir
        if memo:
            with open(os.path.join(output_dir, "memo.txt"), "w", encoding="utf-8") as memo_file:
                memo_file.write(memo)

        formatter = _LogFormatter(
            direction=self.direction,
            use_relative_score=self.use_relative_score,
            total_files=len(self.input_file_names),
            is_int=self.is_int,
        )
        run_config = _RunConfig(
            command=self.execute_command + self.added_command,
            timeout=self.timeout,
            use_relative_score=self.use_relative_score,
            baseline_scores=self.pre_data,
            verbose=self.verbose,
            direction=self.direction,
            output_dir=output_dir,
            record=record,
            is_int=self.is_int,
            formatter=formatter,
        )
        worker_state = WorkerState()
        worker_arguments = [(input_file, run_config, worker_state) for input_file in self.input_file_names]

        results = self._map_in_parallel(_worker_process_file, worker_arguments)

        results.sort(key=lambda result: result[0])
        self._write_result_csv(output_dir, results)
        if record:
            self._copy_outputs_to_local(output_dir)
        return results

    @staticmethod
    def get_args() -> argparse.Namespace:
        """実行時引数を解析する"""
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-c",
            "--compile",
            required=False,
            action="store_true",
            default=False,
            help="if compile the file. default is `False`.",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            required=False,
            action="store_true",
            default=False,
            help="show logs. default is `False`.",
        )
        parser.add_argument(
            "--cpu-affinity",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="ケースごとの CPU 固定を切り替える (未指定時は settings に従う)",
        )
        return parser.parse_args()


def build_tester(
    settings: AHCSettings,
    njobs: int,
    verbose: bool = False,
    cpu_affinity: bool = False,
    affinity_cpu_ids: Optional[tuple[int, ...]] = None,
    cpu_locks: Optional[Mapping[int, CpuLock]] = None,
) -> ParallelTester:
    """`AHCSettings` から `ParallelTester` を組み立てて返す"""
    if affinity_cpu_ids is None:
        affinity_cpu_ids = get_cpu_affinity_ids(njobs) if cpu_affinity else ()
    cpu_count = len(affinity_cpu_ids) if affinity_cpu_ids else min(njobs, multiprocessing.cpu_count() - 1)
    tester = ParallelTester(
        direction=settings.direction,
        filename=settings.filename,
        compile_command=settings.compile_command,
        execute_command=settings.execute_command,
        input_file_names=settings.input_file_names,
        cpu_count=cpu_count,
        verbose=verbose,
        get_score=settings.get_score,
        timeout=settings.timeout,
        use_relative_score=settings.use_relative_score,
        pre_dir_name=settings.pre_dir_name,
        is_int=settings.is_int,
        optuna_seed=settings.optuna_seed,
        cpu_ids=affinity_cpu_ids,
        cpu_locks=cpu_locks,
    )
    return tester


def _summarize_relative_scores(
    relative_scores: list[float],
) -> tuple[int, int, int, float, int]:
    """相対スコアを 1 未満、同値、1 超、対数平均、欠損件数に集計する"""
    error_count = relative_scores.count(-1)
    lower_count = equal_count = upper_count = 0
    log_sum = 0.0
    for relative_score in relative_scores:
        if math.isnan(relative_score) or relative_score == -1:
            continue
        log_sum += math.log(relative_score)
        if relative_score < 1.0:
            lower_count += 1
        elif relative_score == 1.0:
            equal_count += 1
        else:
            upper_count += 1
    valid_count = lower_count + equal_count + upper_count
    average = math.exp(log_sum / valid_count) if valid_count > 0 else math.nan
    return lower_count, equal_count, upper_count, average, error_count


def _log_relative_score_summary(scores: list[CaseResult], direction: Direction) -> None:
    """相対スコアの改善、同値、悪化件数と平均を出力する"""
    relative_scores = [relative_score for _, _, relative_score, _, _ in scores]
    (
        lower_count,
        equal_count,
        upper_count,
        average_relative_score,
        error_count,
    ) = _summarize_relative_scores(relative_scores)
    if error_count:
        logger.error(to_red(f"RelativeScore::ErrorCount: {error_count}."))
    # minimize では 1 未満、maximize では 1 超を改善として扱う
    if direction == "minimize":
        improved_count, worsened_count = lower_count, upper_count
    else:
        improved_count, worsened_count = upper_count, lower_count
    logger.info(f"Better : {_format_count(improved_count, True)}.")
    logger.info(f"Same   : {equal_count}.")
    logger.info(f"Worse  : {_format_count(worsened_count, False)}.")
    logger.info(f"RelativeScore: " f"{_format_relative_score(average_relative_score, direction)}.")


ERROR_TABLE_STATES: tuple[SolverState, ...] = ("TLE", "ERROR", "INNER_ERROR")


def _log_error_table(failed_cases: list[tuple[str, SolverState]]) -> None:
    """失敗した入力ファイルを終了状態ごとに一覧表示する"""
    maximum_label_width = max(len(f" {label} ") for label in ERROR_TABLE_STATES)
    maximum_filename_width = max(len(filename) for filename, _ in failed_cases)
    table_width = max(maximum_label_width, maximum_filename_width) + 2
    separator = "=" * (table_width + 2)
    section_separator = "-" * (table_width + 2)

    logger.error(separator)
    logger.error(to_red(f"ErrorCount: {len(failed_cases)}."))

    state_counts = collections.Counter(state for _, state in failed_cases)
    for label in ERROR_TABLE_STATES:
        logger.error(section_separator)
        header = f" {label} "
        logger.error("|" + header + " " * (table_width - len(header)) + "|")
        for filename, state in failed_cases:
            if state == label:
                logger.error("|" + to_red(f" {filename} ") + "|")

    logger.error(section_separator)
    logger.error(separator)
    logger.error(to_red(f" TLE   : {state_counts['TLE']} "))
    logger.error(to_red(f" Other : {state_counts['ERROR']} "))
    logger.error(to_red(f" Inner : {state_counts['INNER_ERROR']} "))


def _log_settings(settings: AHCSettings, njobs: int, cpu_ids: tuple[int, ...]) -> None:
    logger.info(f"--- {to_bold('[Settings]')} ---")
    logger.info(f"direction       : {settings.direction}")
    logger.info(f"timeout         : {settings.timeout}")
    logger.info(f"filename        : {to_bold(to_blue((settings.filename)))}")
    if settings.use_relative_score:
        logger.info(f"pre_dir_name    : {settings.pre_dir_name}")
    logger.info(f"execute_command : {settings.execute_command}")
    logger.info(f"njobs           : {njobs}")
    cpu_affinity = ", ".join(map(str, cpu_ids)) if cpu_ids else "disabled"
    logger.info(f"cpu affinity    : {cpu_affinity}")
    logger.info("----------------")


def run_test(
    settings: AHCSettings,
    njobs: int,
    verbose: bool = False,
    compile: bool = False,
    record: bool = True,
    memo: Optional[str] = None,
    cpu_affinity: bool = False,
) -> float:
    configure_elapsed_logging()

    if not cpu_affinity:
        njobs = max(1, min(njobs, multiprocessing.cpu_count() - 1))

    tester = build_tester(settings, njobs, verbose, cpu_affinity=cpu_affinity)

    if verbose:
        _log_settings(settings, max(1, tester.cpu_count), tester.cpu_ids)

    if compile:
        if verbose:
            logger.info(f"Compiling...    : {settings.compile_command}")
        tester.compile()

    if verbose:
        logger.info("Start.")

    start = time.time()

    scores = tester.run_record(record, memo)

    if settings.use_relative_score:
        _log_relative_score_summary(scores, settings.direction)

    failed_cases = [(filename, state) for filename, score, _, state, _ in scores if math.isnan(score)]
    if failed_cases:
        _log_error_table(failed_cases)

    score = tester.show_score([case_score for _, case_score, _, _, _ in scores])
    logger.info(to_green(f"Finished in {time.time() - start:.4f} sec."))
    if tester.last_output_dir is not None:
        logger.info(f"Result directory: {to_bold(to_blue(tester.last_output_dir))}")
    return score


def main() -> None:
    """コマンドライン引数を読み、並列テストを実行する"""
    args = ParallelTester.get_args()
    njobs = min(AHCSettings.njobs, multiprocessing.cpu_count() - 1)
    cpu_affinity = bool(getattr(AHCSettings, "cpu_affinity", False)) if args.cpu_affinity is None else args.cpu_affinity
    run_test(
        AHCSettings,
        njobs,
        args.verbose,
        args.compile,
        True,
        cpu_affinity=cpu_affinity,
    )


if __name__ == "__main__":
    main()
