from typing import Iterable, Callable, Optional, Literal, Union, ClassVar
import argparse
import collections
import concurrent.futures
from dataclasses import dataclass, field
from logging import getLogger, basicConfig
import subprocess
import multiprocessing
import time
import math
import os
import sys
from random import Random
import shutil
import csv
import threading
import optuna
import datetime
import pandas as pd
from .ahc_settings import AHCSettings
from .ahc_util import to_green, to_red, to_bold, to_blue

logger = getLogger(__name__)

# --- 単位変換 ---
MS_PER_SEC = 1000

# --- スコア取得フォーマット (`Score = X` を前提) ---
SCORE_DELIMITER = " = "

# --- ディレクトリ / ファイル構成 ---
RESULTS_DIR = "ahclib_results"
ALL_TESTS_SUBDIR = "all_tests"
RESULT_CSV = "result.csv"
ERR_SUBDIR = "err"
OUT_SUBDIR = "out"
LOCAL_OUT_DIR = "./out/"
SETTINGS_FILE = "ahc_settings.py"

# --- CSV ---
CSV_HEADERS_REL = ["filename", "score", "rel_score", "state", "time"]
CSV_HEADERS_NOREL = ["filename", "score", "state", "time"]

SolverState = Literal["AC", "TLE", "ERROR", "INNER_ERROR"]
Direction = Literal["minimize", "maximize"]
Score = Union[int, float]
CaseResult = tuple[str, Score, float, SolverState, str]

# 並列実行は subprocess での外部プロセス起動が主体なので
# GIL の影響を受けにくく ThreadPoolExecutor で十分
# ProcessPoolExecutor に置き換えると WorkerState の共有や
# worker 関数の pickling が問題になるので注意


@dataclass
class WorkerState:
    """worker 間で共有する集計状態 ロック下で更新する"""

    lock: threading.Lock = field(default_factory=threading.Lock)
    counter: int = 0
    score_sum: float = 0.0
    valid_cnt: int = 0
    rel_log_sum: float = 0.0
    rel_cnt: int = 0
    rel_good_cnt: int = 0
    rel_same_cnt: int = 0
    rel_bad_cnt: int = 0


def _decode_proc_output(s: Union[str, bytes, None]) -> str:
    if s is None:
        return ""
    return s if isinstance(s, str) else s.decode("utf-8", errors="ignore")


def _execute_solver(
    input_file: str,
    cmd: list[str],
    timeout: Optional[float],
    is_int: bool,
) -> tuple[SolverState, Score, str, str, float]:
    """`input_file` を stdin に渡して `cmd` を実行し `(state, score, stdout, stderr, elapsed)` を返す (AC 以外は score=nan)"""
    with open(input_file, "r", encoding="utf-8") as f:
        input_text = f.read()
    try:
        start = time.perf_counter()
        result = subprocess.run(
            cmd,
            input=input_text,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=True,
        )
        elapsed = time.perf_counter() - start
        score_line = result.stderr.rstrip().split("\n")[-1]
        _, score_str = score_line.split(SCORE_DELIMITER)
        score = int(score_str) if is_int else float(score_str)
        return "AC", score, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired as e:
        elapsed = timeout if timeout is not None else -1.0
        return (
            "TLE",
            math.nan,
            _decode_proc_output(e.stdout),
            _decode_proc_output(e.stderr),
            elapsed,
        )
    except subprocess.CalledProcessError as e:
        return "ERROR", math.nan, e.stdout or "", e.stderr or "", -1.0
    except Exception as e:
        logger.exception(e)
        return "INNER_ERROR", math.nan, "", "", -1.0


def _calc_relative_score(
    score: Score, input_file: str, pre_data: dict[str, float]
) -> float:
    """`score / pre_data[input_file]` を返す `input_file` が `pre_data` になければ -1.0"""
    if input_file not in pre_data:
        return -1.0
    return score / pre_data[input_file]


def _format_rel_score(rel_score: float, direction: Direction, fmt: str = ".4f") -> str:
    """相対スコアを direction に応じた色付き文字列にして返す"""
    if math.isnan(rel_score):
        return to_red("nan")
    if rel_score == -1:
        return to_red(f"{rel_score:{fmt}}")
    s = f"{rel_score:{fmt}}"
    if rel_score == 1.0:
        return s
    is_good = (rel_score < 1.0) if direction == "minimize" else (rel_score > 1.0)
    return to_green(s) if is_good else to_red(s)


def _format_count(cnt: int, is_good: bool) -> str:
    """件数表示用 良い側なら緑 悪い側なら赤で返す"""
    return to_green(cnt) if is_good else to_red(cnt)


def _log_solver_error(input_file: str, state: SolverState) -> None:
    """`_execute_solver` の非ACステートに対応するエラーログを出力する"""
    if state == "TLE":
        logger.error(to_red(f"TLE occured in {input_file}"))
    elif state == "ERROR":
        logger.error(to_red(f"Error occured in {input_file}"))
    elif state == "INNER_ERROR":
        logger.error(to_red(f"!!! Error occured in {input_file}"))


def _write_record(output_dir: str, filename: str, stdout: str, stderr: str) -> None:
    """{output_dir}/err/{filename} と {output_dir}/out/{filename} に書き出す"""
    with open(
        os.path.join(output_dir, ERR_SUBDIR, filename), "w", encoding="utf-8"
    ) as f:
        f.write(stderr)
    with open(
        os.path.join(output_dir, OUT_SUBDIR, filename), "w", encoding="utf-8"
    ) as f:
        f.write(stdout)


@dataclass
class _LogFormatter:
    """per-case ログ整形をまとめるクラス direction / use_rel / total_files / is_int に依存する整形を集約"""

    KETA_SCORE: ClassVar[int] = 10
    KETA_TIME: ClassVar[int] = 11

    direction: Direction
    use_relative_score: bool
    total_files: int
    is_int: bool

    def _cnt_keta(self) -> int:
        return len(str(self.total_files))

    def format_score(self, score: Score) -> str:
        return (
            f"{score:>{self.KETA_SCORE}}"
            if self.is_int
            else f"{score:>{self.KETA_SCORE}.3f}"
        )

    def format_ave_score(self, ave: float) -> str:
        return f"{ave:>{self.KETA_SCORE}.3f}"

    def format_time(self, elapsed: float) -> str:
        return f"{f'{elapsed:.3f} sec':>{self.KETA_TIME}}"

    def format_tle_time(self, timeout: float) -> str:
        return f"{f'>{timeout:.3f} sec':>{self.KETA_TIME}}"

    def format_cnt(self, cnt: int) -> str:
        return f"{cnt:>{self._cnt_keta()}}"

    def format_rel_cnts(self, good: int, same: int, bad: int) -> str:
        keta = self._cnt_keta()
        g = f"{good:>{keta}}"
        s = f"{same:>{keta}}"
        b = f"{bad:>{keta}}"
        return f"{to_green(g)} / {s} / {to_red(b)}"

    def format_rel_score(self, rel: float, fmt: str = ".4f") -> str:
        return _format_rel_score(rel, self.direction, fmt)

    def build_ac_line(
        self,
        cnt: int,
        input_file: str,
        score: Score,
        elapsed: float,
        relative_score: float,
        ave_score: float,
        rel_ave_str: str,
        rel_cnt_str: str,
    ) -> str:
        parts = [
            f"{self.format_cnt(cnt)} / {self.total_files}",
            input_file,
            self.format_score(score),
            self.format_time(elapsed),
        ]
        if self.use_relative_score:
            parts.extend(
                [
                    self.format_rel_score(relative_score, fmt=".3f"),
                    f"Ave: {self.format_ave_score(ave_score)}",
                    f"RelAve: {rel_ave_str}",
                    f"Better/Same/Worse: {rel_cnt_str}",
                ]
            )
        else:
            parts.append(f"Ave: {self.format_ave_score(ave_score)}")
        return f"| {' | '.join(parts)} |"

    def build_tle_line(self, cnt: int, input_file: str, timeout: float) -> str:
        s = "-" * self.KETA_SCORE
        t = self.format_tle_time(timeout)
        return f"| {self.format_cnt(cnt)} / {self.total_files} | {input_file} | {s} | {to_red(t)} |"


@dataclass
class _RunCfg:
    """`_worker_process_file` 系に渡すラン全体の設定 immutable に扱う"""

    cmd: list[str]
    timeout: Optional[float]
    use_relative_score: bool
    pre_data: dict[str, float]
    verbose: bool
    direction: Direction
    output_dir: str
    record: bool
    is_int: bool
    formatter: _LogFormatter


def _run_case_for_opt(
    input_file: str,
    cmd: list[str],
    timeout: Optional[float],
    is_int: bool,
    use_relative_score: bool,
    pre_data: dict[str, float],
) -> float:
    """1ケース実行しスコアを返す (Optuna 用) 失敗時は nan"""
    state, score, _, _, _ = _execute_solver(input_file, cmd, timeout, is_int)
    if state != "AC":
        _log_solver_error(input_file, state)
        return math.nan
    if use_relative_score:
        return _calc_relative_score(score, input_file, pre_data)
    return score


def _worker_process_file_opt_pruner(args) -> tuple[int, float]:
    input_file, id_, cmd, timeout, is_int, use_relative_score, pre_data = args
    score = _run_case_for_opt(
        input_file, cmd, timeout, is_int, use_relative_score, pre_data
    )
    return id_, score


def _worker_process_file_light(args) -> float:
    """入力 `input_file` を処理する (軽量版)"""
    input_file, cmd, timeout, is_int, use_relative_score, pre_data = args
    return _run_case_for_opt(
        input_file, cmd, timeout, is_int, use_relative_score, pre_data
    )


def _increment_counter(state: WorkerState) -> int:
    """`state.counter` をロック下で 1 進めて新しい値を返す"""
    with state.lock:
        state.counter += 1
        return state.counter


def _update_running_stats(
    state: WorkerState,
    formatter: _LogFormatter,
    score: Score,
    relative_score: float,
) -> tuple[int, float, str, str]:
    """ロック下でカウンタを更新し `(cnt, ave_score, rel_ave_str, rel_cnt_str)` を返す (use_relative_score=False のとき rel_* は空文字)"""
    with state.lock:
        state.counter += 1
        cnt = state.counter
        if not math.isnan(score):
            state.score_sum += score
            state.valid_cnt += 1
        valid = state.valid_cnt
        ave_score = state.score_sum / valid if valid > 0 else 0.0

        rel_ave_str = ""
        rel_cnt_str = ""
        if formatter.use_relative_score:
            if not math.isnan(relative_score) and relative_score != -1:
                state.rel_log_sum += math.log(relative_score)
                state.rel_cnt += 1
                if relative_score == 1.0:
                    state.rel_same_cnt += 1
                else:
                    is_good = (
                        (relative_score < 1.0)
                        if formatter.direction == "minimize"
                        else (relative_score > 1.0)
                    )
                    if is_good:
                        state.rel_good_cnt += 1
                    else:
                        state.rel_bad_cnt += 1
            rel_cnt_str = formatter.format_rel_cnts(
                state.rel_good_cnt, state.rel_same_cnt, state.rel_bad_cnt
            )
            if state.rel_cnt > 0:
                ave_rel = math.exp(state.rel_log_sum / state.rel_cnt)
                rel_ave_str = formatter.format_rel_score(ave_rel)
            else:
                rel_ave_str = to_red("nan")
    return cnt, ave_score, rel_ave_str, rel_cnt_str


def _handle_ac_case(
    input_file: str,
    score: Score,
    stdout: str,
    stderr: str,
    elapsed: float,
    cfg: _RunCfg,
    state: WorkerState,
) -> CaseResult:
    relative_score = _calc_relative_score(score, input_file, cfg.pre_data)
    if cfg.verbose:
        cnt, ave_score, rel_ave_str, rel_cnt_str = _update_running_stats(
            state, cfg.formatter, score, relative_score
        )
        logger.info(
            cfg.formatter.build_ac_line(
                cnt,
                input_file,
                score,
                elapsed,
                relative_score,
                ave_score,
                rel_ave_str,
                rel_cnt_str,
            )
        )
    if cfg.record:
        _write_record(cfg.output_dir, os.path.basename(input_file), stdout, stderr)
    return input_file, score, relative_score, "AC", f"{elapsed:.3f}"


def _handle_tle_case(
    input_file: str,
    stdout: str,
    stderr: str,
    cfg: _RunCfg,
    state: WorkerState,
) -> CaseResult:
    cnt = _increment_counter(state)
    if cfg.verbose:
        logger.info(cfg.formatter.build_tle_line(cnt, input_file, cfg.timeout))
    if cfg.record:
        _write_record(cfg.output_dir, os.path.basename(input_file), stdout, stderr)
    return input_file, math.nan, math.nan, "TLE", f"{cfg.timeout:.3f}"


def _handle_error_case(
    input_file: str,
    solver_state: SolverState,
    stdout: str,
    stderr: str,
    cfg: _RunCfg,
    state: WorkerState,
) -> CaseResult:
    _increment_counter(state)
    if solver_state == "ERROR" and cfg.record:
        _write_record(cfg.output_dir, os.path.basename(input_file), stdout, stderr)
    _log_solver_error(input_file, solver_state)
    return input_file, math.nan, math.nan, solver_state, "-1"


def _worker_process_file(args) -> CaseResult:
    """入力 `input_file` を処理しログやファイル出力も行う"""
    input_file, cfg, state = args
    solver_state, score, stdout, stderr, elapsed = _execute_solver(
        input_file, cfg.cmd, cfg.timeout, cfg.is_int
    )
    if solver_state == "AC":
        return _handle_ac_case(input_file, score, stdout, stderr, elapsed, cfg, state)
    if solver_state == "TLE":
        return _handle_tle_case(input_file, stdout, stderr, cfg, state)
    return _handle_error_case(input_file, solver_state, stdout, stderr, cfg, state)


def _submit_next(
    executor: concurrent.futures.Executor,
    args_iter,
    futures: dict,
    worker_func: Callable,
) -> None:
    """`args_iter` から次の args を取り出して `executor` に submit する 既に尽きていれば何もしない"""
    try:
        next_args = next(args_iter)
    except StopIteration:
        return
    futures[executor.submit(worker_func, next_args)] = next_args


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
    ) -> None:
        """ParallelTester を初期化する

        Args:
            direction: `"minimize"` か `"maximize"` ログの色付けに使う
            compile_command: コンパイルコマンド (`None` ならコンパイルしない)
            execute_command: 実行コマンド (引数は `append_execute_command` でも追加可)
            input_file_names: 入力ファイル名のリスト
            cpu_count: 並列ワーカ数
            verbose: per-case ログを表示するか
            get_score: スコアのリストを集約する関数 (平均など)
            timeout: 1ケースのタイムアウト [ms] (`None` で無制限)
            is_int: スコアが整数なら True 小数なら False
            optuna_seed: `run_opt_pruner` の入力順シャッフル用シード
        """
        if direction != "minimize" and direction != "maximize":
            logger.critical(
                f"direction must be `minimize` or `maximize` but got {direction}."
            )
            raise ValueError(f"Invalid direction: {direction}")

        self.direction = direction
        self.filename = filename
        self.compile_command = compile_command.split() if compile_command else None
        self.execute_command = execute_command.split()
        self.added_command: list[str] = []
        self.input_file_names = input_file_names
        self.cpu_count = cpu_count
        self.verbose = verbose
        self.get_score = get_score
        self.timeout = (
            timeout / MS_PER_SEC if (timeout is not None) and (timeout >= 0) else None
        )
        self.use_relative_score = use_relative_score
        self.is_int = is_int
        pre_csv = os.path.join(
            RESULTS_DIR, ALL_TESTS_SUBDIR, pre_dir_name, RESULT_CSV
        )
        self.pre_data: dict[str, float] = {}
        if os.path.exists(pre_csv):
            df = pd.read_csv(pre_csv)
            self.pre_data = dict(zip(df["filename"], df["score"]))

        # `self.rnd` は run_opt_pruner で入力順をシャッフルするのに使う
        self.rnd = Random(optuna_seed)

    def show_score(self, scores: list[float]) -> float:
        """スコアのリストを受け取り `get_score` 関数で計算する ついでに表示もする"""
        score = self.get_score(scores)
        logger.info(f"Ave.{score}")
        return score

    def append_execute_command(self, args: Iterable[object]) -> None:
        """コマンドライン引数を追加する (`str()` 変換されるので int/float もそのまま渡せる)"""
        for arg in args:
            self.added_command.append(str(arg))

    def clear_execute_command(self) -> None:
        """これまでに追加したコマンドライン引数を削除する"""
        self.added_command.clear()

    def compile(self) -> None:
        """`compile_command` よりコンパイルする 失敗時はエラーログを出して終了する"""
        if self.compile_command is None:
            return
        try:
            subprocess.run(
                self.compile_command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(to_red("Compile failed"))
            if e.stderr:
                logger.error(e.stderr.rstrip())
            sys.exit(1)

    def _map_in_parallel(self, worker_func: Callable, args_list: list) -> list:
        """ThreadPool で `worker_func` を `args_list` 全件に適用しリストで返す"""
        max_workers = max(1, self.cpu_count)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(worker_func, args_list))

    def run_opt_pruner(self, trial: optuna.trial.Trial) -> list[Optional[float]]:
        """Optuna trial 用に並列実行し pruner が `should_prune` を返したら打ち切る

        Returns:
            各ケースのスコアリスト 打ち切られたケースは `None` のまま残る
        """
        scores_list: list[Optional[float]] = [None] * len(self.input_file_names)
        input_filenames = list(enumerate(self.input_file_names))
        self.rnd.shuffle(input_filenames)

        cmd = self.execute_command + self.added_command
        args_list = [
            (
                file,
                id_,
                cmd,
                self.timeout,
                self.is_int,
                self.use_relative_score,
                self.pre_data,
            )
            for id_, file in input_filenames
        ]

        max_workers = max(1, self.cpu_count)
        args_iter = iter(args_list)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict = {}
            for _ in range(max_workers):
                _submit_next(
                    executor, args_iter, futures, _worker_process_file_opt_pruner
                )

            while futures:
                done, _ = concurrent.futures.wait(
                    futures, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    futures.pop(future)
                    id_, score = future.result()
                    trial.report(score, id_)
                    scores_list[id_] = score
                    if trial.should_prune():
                        # 注: 実行中の future は cancel しても止まらない
                        #     まだ実行開始されていないものだけ取り消せる
                        for pending in futures:
                            pending.cancel()
                        return scores_list
                    _submit_next(
                        executor, args_iter, futures, _worker_process_file_opt_pruner
                    )
        return scores_list

    def run(self) -> list[float]:
        """全ケースを並列実行しスコアリストだけ返す (ログ・記録なし)"""
        cmd = self.execute_command + self.added_command
        args_list = [
            (
                file,
                cmd,
                self.timeout,
                self.is_int,
                self.use_relative_score,
                self.pre_data,
            )
            for file in self.input_file_names
        ]
        return self._map_in_parallel(_worker_process_file_light, args_list)

    def _create_output_dir(self) -> str:
        """タイムスタンプ付きの出力ディレクトリを作って返す 既存なら例外"""
        dt_now = datetime.datetime.now()
        output_dir = os.path.join(
            RESULTS_DIR, ALL_TESTS_SUBDIR, dt_now.strftime("%Y-%m-%d_%H-%M-%S")
        )
        if os.path.exists(output_dir):
            logger.error(
                to_red(
                    f"Output dir already exists (aborting to avoid overwrite): {output_dir}"
                )
            )
            raise FileExistsError(output_dir)
        os.makedirs(output_dir)
        return output_dir

    def _copy_source_files(self, output_dir: str) -> None:
        """main ファイルと `ahc_settings.py` を `output_dir` 配下にコピーする"""
        src_basename = os.path.basename(self.filename)
        try:
            shutil.copy2(self.filename, os.path.join(output_dir, src_basename))
        except Exception as e:
            logger.warning(f"Failed to copy source file {self.filename}: {e}")
        try:
            shutil.copy2(SETTINGS_FILE, os.path.join(output_dir, SETTINGS_FILE))
        except Exception as e:
            logger.warning(f"Failed to copy {SETTINGS_FILE}: {e}")

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

    def _write_result_csv(self, output_dir: str, result: list[CaseResult]) -> None:
        """`{output_dir}/result.csv` へ書き出す"""
        csv_path = os.path.join(output_dir, RESULT_CSV)
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            if self.use_relative_score:
                writer.writerow(CSV_HEADERS_REL)
                for filename, score, rel_score, state, t in result:
                    writer.writerow([filename, score, rel_score, state, t])
            else:
                writer.writerow(CSV_HEADERS_NOREL)
                for filename, score, _, state, t in result:
                    writer.writerow([filename, score, state, t])

    def _copy_outputs_to_local(self, output_dir: str) -> None:
        """`{output_dir}/out/` の中身を `./out/` にコピーする"""
        if not os.path.exists(LOCAL_OUT_DIR):
            os.makedirs(LOCAL_OUT_DIR)
        src_out = os.path.join(output_dir, OUT_SUBDIR)
        for item in os.listdir(src_out):
            src_path = os.path.join(src_out, item)
            dest_path = os.path.join(LOCAL_OUT_DIR, item)
            if os.path.isfile(src_path):
                shutil.copy2(src_path, dest_path)
            elif os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path)

    def run_record(self, record: bool) -> list[CaseResult]:
        """全ケースを並列実行し CSV と (record=True なら) 入出力ファイルも保存する"""
        output_dir = self._setup_output_dir(record)

        formatter = _LogFormatter(
            direction=self.direction,
            use_relative_score=self.use_relative_score,
            total_files=len(self.input_file_names),
            is_int=self.is_int,
        )
        cfg = _RunCfg(
            cmd=self.execute_command + self.added_command,
            timeout=self.timeout,
            use_relative_score=self.use_relative_score,
            pre_data=self.pre_data,
            verbose=self.verbose,
            direction=self.direction,
            output_dir=output_dir,
            record=record,
            is_int=self.is_int,
            formatter=formatter,
        )
        worker_state = WorkerState()
        args_list = [(file, cfg, worker_state) for file in self.input_file_names]

        result = self._map_in_parallel(_worker_process_file, args_list)

        result.sort(key=lambda r: r[0])
        self._write_result_csv(output_dir, result)
        if record:
            self._copy_outputs_to_local(output_dir)
        return result

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
        return parser.parse_args()


def build_tester(
    settings: AHCSettings, njobs: int, verbose: bool = False
) -> ParallelTester:
    """`AHCSettings` から `ParallelTester` を組み立てて返す"""
    tester = ParallelTester(
        direction=settings.direction,
        filename=settings.filename,
        compile_command=settings.compile_command,
        execute_command=settings.execute_command,
        input_file_names=settings.input_file_names,
        cpu_count=min(njobs, multiprocessing.cpu_count() - 1),
        verbose=verbose,
        get_score=settings.get_score,
        timeout=settings.timeout,
        use_relative_score=settings.use_relative_score,
        pre_dir_name=settings.pre_dir_name,
        is_int=settings.is_int,
        optuna_seed=settings.optuna_seed,
    )
    return tester


def _summarize_relative_scores(
    relative_scores: list[float],
) -> tuple[int, int, int, float, int]:
    """相対スコアのリストから `(less_cnt, same_cnt, upper_cnt, ave_rel, error_cnt)` を返す (error_cnt は -1 の件数 ave_rel は対数平均で有効値ゼロなら nan)"""
    error_cnt = relative_scores.count(-1)
    less_cnt = same_cnt = upper_cnt = 0
    log_sum = 0.0
    for r in relative_scores:
        if math.isnan(r) or r == -1:
            continue
        log_sum += math.log(r)
        if r < 1.0:
            less_cnt += 1
        elif r == 1.0:
            same_cnt += 1
        else:
            upper_cnt += 1
    total = less_cnt + same_cnt + upper_cnt
    ave = math.exp(log_sum / total) if total > 0 else math.nan
    return less_cnt, same_cnt, upper_cnt, ave, error_cnt


def _log_relative_score_summary(scores: list[CaseResult], direction: Direction) -> None:
    """相対スコアの集計結果 (Better/Same/Worse/平均) を出力する"""
    relative_scores = [r for _, _, r, _, _ in scores]
    less_cnt, same_cnt, upper_cnt, ave_rel, error_cnt = _summarize_relative_scores(
        relative_scores
    )
    if error_cnt:
        logger.error(to_red(f"RelativeScore::ErrorCount: {error_cnt}."))
    # minimize: less (rel<1) が改善側 / maximize: upper (rel>1) が改善側
    if direction == "minimize":
        better_cnt, worse_cnt = less_cnt, upper_cnt
    else:
        better_cnt, worse_cnt = upper_cnt, less_cnt
    logger.info(f"Better : {_format_count(better_cnt, True)}.")
    logger.info(f"Same   : {same_cnt}.")
    logger.info(f"Worse  : {_format_count(worse_cnt, False)}.")
    logger.info(f"RelativeScore: {_format_rel_score(ave_rel, direction)}.")


ERROR_TABLE_STATES: tuple[SolverState, ...] = ("TLE", "ERROR", "INNER_ERROR")


def _log_error_table(nan_case: list[tuple[str, SolverState]]) -> None:
    """TLE / ERROR / INNER_ERROR の入力ファイル一覧をテーブル形式で出力する"""
    label_max = max(len(f" {label} ") for label in ERROR_TABLE_STATES)
    filename_max = max(len(f) for f, _ in nan_case)
    delta = max(label_max, filename_max) + 2
    sep = "=" * (delta + 2)
    minor = "-" * (delta + 2)

    logger.error(sep)
    logger.error(to_red(f"ErrorCount: {len(nan_case)}."))

    cnts = collections.Counter(state for _, state in nan_case)
    for label in ERROR_TABLE_STATES:
        logger.error(minor)
        header = f" {label} "
        logger.error("|" + header + " " * (delta - len(header)) + "|")
        for f, state in nan_case:
            if state == label:
                logger.error("|" + to_red(f" {f} ") + "|")

    logger.error(minor)
    logger.error(sep)
    logger.error(to_red(f" TLE   : {cnts['TLE']} "))
    logger.error(to_red(f" Other : {cnts['ERROR']} "))
    logger.error(to_red(f" Inner : {cnts['INNER_ERROR']} "))


def _log_settings(settings: AHCSettings, njobs: int) -> None:
    logger.info(f"--- {to_bold('[Settings]')} ---")
    logger.info(f"direction       : {settings.direction}")
    logger.info(f"timeout         : {settings.timeout}")
    logger.info(f"filename        : {to_bold(to_blue((settings.filename)))}")
    if settings.use_relative_score:
        logger.info(f"pre_dir_name    : {settings.pre_dir_name}")
    logger.info(f"execute_command : {settings.execute_command}")
    logger.info(f"njobs           : {njobs}")
    logger.info("----------------")


def run_test(
    settings: AHCSettings,
    njobs: int,
    verbose: bool = False,
    compile: bool = False,
    record: bool = True,
) -> float:
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    njobs = max(1, min(njobs, multiprocessing.cpu_count() - 1))

    if verbose:
        _log_settings(settings, njobs)

    tester = build_tester(settings, njobs, verbose)

    if compile:
        if verbose:
            logger.info(f"Compiling...    : {settings.compile_command}")
        tester.compile()

    if verbose:
        logger.info("Start.")

    start = time.time()

    scores = tester.run_record(record)

    if settings.use_relative_score:
        _log_relative_score_summary(scores, settings.direction)

    nan_case = [
        (filename, state) for filename, s, _, state, _ in scores if math.isnan(s)
    ]
    if nan_case:
        _log_error_table(nan_case)

    score = tester.show_score([s for _, s, _, _, _ in scores])
    logger.info(to_green(f"Finished in {time.time() - start:.4f} sec."))
    return score


def main():
    """実行時引数をもとに `tester` を立ち上げ実行する"""
    args = ParallelTester.get_args()
    njobs = min(AHCSettings.njobs, multiprocessing.cpu_count() - 1)
    run_test(AHCSettings, njobs, args.verbose, args.compile, True)


if __name__ == "__main__":
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    main()
