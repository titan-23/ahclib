from typing import Iterable, Callable, Optional
import argparse
import concurrent.futures
from logging import getLogger, basicConfig
import subprocess
import multiprocessing
import time
import math
import os
from random import Random
import shutil
import csv
import threading
from types import SimpleNamespace
import optuna
import datetime
import pandas as pd
from .ahc_settings import AHCSettings
from .ahc_util import to_green, to_red, to_bold, to_blue

logger = getLogger(__name__)

KETA_SCORE = 10
KETA_TIME = 11
KETA_REL_SCORE = 10

worker_lock = None
worker_counter = None
worker_score_sum = None
worker_valid_cnt = None
worker_rel_log_sum = None
worker_rel_cnt = None
worker_rel_good_cnt = None
worker_rel_same_cnt = None
worker_rel_bad_cnt = None


def init_worker(
    lock,
    counter,
    score_sum,
    valid_cnt,
    rel_log_sum,
    rel_cnt,
    rel_good_cnt,
    rel_same_cnt,
    rel_bad_cnt,
):
    """各ワーカープロセスの初期化時に呼ばれ、LockとCounterをセットします。"""
    global worker_lock, worker_counter, worker_score_sum, worker_valid_cnt
    global worker_rel_log_sum, worker_rel_cnt
    global worker_rel_good_cnt, worker_rel_same_cnt, worker_rel_bad_cnt
    worker_lock = lock
    worker_counter = counter
    worker_score_sum = score_sum
    worker_valid_cnt = valid_cnt
    worker_rel_log_sum = rel_log_sum
    worker_rel_cnt = rel_cnt
    worker_rel_good_cnt = rel_good_cnt
    worker_rel_same_cnt = rel_same_cnt
    worker_rel_bad_cnt = rel_bad_cnt


def worker_process_file_opt_wilcoxon(args) -> tuple[int, float]:
    input_file, id_, cmd, timeout, use_relative_score, pre_data = args
    with open(input_file, "r", encoding="utf-8") as f:
        input_text = f.read()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            input=input_text,
            timeout=timeout,
            text=True,
            check=True,
        )
        score_line = result.stderr.rstrip().split("\n")[-1]
        _, score = score_line.split(" = ")
        score = float(score)
        if use_relative_score:
            score = -1 if input_file not in pre_data else score / pre_data[input_file]
        return id_, score
    except subprocess.TimeoutExpired:
        logger.error(to_red(f"TLE occured in {input_file}"))
        return id_, math.nan
    except subprocess.CalledProcessError:
        logger.error(to_red(f"Error occured in {input_file}"))
        return id_, math.nan
    except Exception as e:
        logger.exception(e)
        logger.error(to_red(f"!!! Error occured in {input_file}"))
        return id_, math.nan


def worker_process_file_light(args) -> float:
    """入力`input_file`を処理します（軽量版）。"""
    input_file, cmd, timeout, use_relative_score, pre_data = args
    with open(input_file, "r", encoding="utf-8") as f:
        input_text = f.read()
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=True,
        )
        score_line = result.stderr.rstrip().split("\n")[-1]
        _, score = score_line.split(" = ")
        score = float(score)
        if use_relative_score:
            score = -1 if input_file not in pre_data else score / pre_data[input_file]
        return score
    except subprocess.TimeoutExpired:
        logger.error(to_red(f"TLE occured in {input_file}"))
        return math.nan
    except subprocess.CalledProcessError:
        logger.error(to_red(f"Error occured in {input_file}"))
        return math.nan
    except Exception as e:
        logger.exception(e)
        logger.error(to_red(f"!!! Error occured in {input_file}"))
        return math.nan


def worker_process_file(args) -> tuple[str, float, float, str, str]:
    """入力`input_file`を処理し、ログやファイル出力も行います。"""
    (
        input_file,
        cmd,
        timeout,
        use_relative_score,
        pre_data,
        verbose,
        direction,
        output_dir,
        record,
        total_files,
    ) = args

    global worker_lock, worker_counter

    with open(input_file, "r", encoding="utf-8") as f:
        input_text = f.read()

    filename = input_file
    if filename.startswith("./"):
        filename = filename[len("./") :]
    filename = filename.split("/", 1)[1]

    try:
        start_time = time.perf_counter()
        result = subprocess.run(
            cmd,
            input=input_text,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=True,
        )
        end_time = time.perf_counter()
        score_line = result.stderr.rstrip().split("\n")[-1]
        _, score = score_line.split(" = ")
        score = float(score) if "." in score else int(score)

        relative_score = (
            -1 if input_file not in pre_data else score / pre_data[input_file]
        )

        if verbose:
            with worker_lock:
                worker_counter.value += 1
                cnt = worker_counter.value
                if not math.isnan(score):
                    worker_score_sum.value += score
                    worker_valid_cnt.value += 1
                now_valid_cnt = worker_valid_cnt.value
                now_ave_score = (
                    worker_score_sum.value / now_valid_cnt if now_valid_cnt > 0 else 0.0
                )
                now_ave_rel_str = ""
                rel_cnt_str = ""
                if use_relative_score:
                    if not math.isnan(relative_score) and relative_score != -1:
                        worker_rel_log_sum.value += math.log(relative_score)
                        worker_rel_cnt.value += 1
                        if relative_score == 1.0:
                            worker_rel_same_cnt.value += 1
                        else:
                            is_good_rel = (
                                (relative_score < 1.0)
                                if direction == "minimize"
                                else (relative_score > 1.0)
                            )
                            if is_good_rel:
                                worker_rel_good_cnt.value += 1
                            else:
                                worker_rel_bad_cnt.value += 1
                    now_rel_cnt = worker_rel_cnt.value
                    rel_cnt_keta = len(str(total_files))
                    good_cnt = f"{worker_rel_good_cnt.value:>{rel_cnt_keta}}"
                    same_cnt = f"{worker_rel_same_cnt.value:>{rel_cnt_keta}}"
                    bad_cnt = f"{worker_rel_bad_cnt.value:>{rel_cnt_keta}}"
                    rel_cnt_str = (
                        f"{to_green(good_cnt)} / {same_cnt} / {to_red(bad_cnt)}"
                    )
                    if now_rel_cnt > 0:
                        ave_rel = math.exp(worker_rel_log_sum.value / now_rel_cnt)
                        is_good_ave = (
                            (ave_rel < 1.0)
                            if direction == "minimize"
                            else (ave_rel > 1.0)
                        )
                        now_ave_rel_str = (
                            f"{ave_rel:.4f}"
                            if ave_rel == 1.0
                            else (
                                to_green(f"{ave_rel:.4f}")
                                if is_good_ave
                                else to_red(f"{ave_rel:.4f}")
                            )
                        )
                    else:
                        now_ave_rel_str = to_red("nan")
            cnt_keta = len(str(total_files))
            cnt_str = f"{cnt:>{cnt_keta}}"
            s = (
                f"{score:>{KETA_SCORE}.3f}"
                if isinstance(score, float)
                else f"{score:>{KETA_SCORE}}"
            )
            t_str = f"{(end_time - start_time):.3f} sec"
            t = f"{t_str:>{KETA_TIME}}"
            ave_s = f"{now_ave_score:>{KETA_SCORE}.3f}"
            log_parts = [f"{cnt_str} / {total_files}", input_file, s, t]
            if use_relative_score:
                if relative_score == -1:
                    u = to_red(f"{relative_score:.3f}")
                else:
                    is_good = (
                        (relative_score < 1.0)
                        if direction == "minimize"
                        else (relative_score > 1.0)
                    )
                    u = (
                        f"{relative_score:.3f}"
                        if relative_score == 1.0
                        else (
                            to_green(f"{relative_score:.3f}")
                            if is_good
                            else to_red(f"{relative_score:.3f}")
                        )
                    )
                log_parts.extend([u, f"Ave: {ave_s}", f"RelAve: {now_ave_rel_str}"])
                log_parts.append(f"Better/Same/Worse: {rel_cnt_str}")
            else:
                log_parts.append(f"Ave: {ave_s}")
            logger.info(f"| {' | '.join(log_parts)} |")

        if record:
            err_path = os.path.join(output_dir, "err", filename)
            with open(err_path, "w", encoding="utf-8") as out_f:
                out_f.write(result.stderr)
            out_path = os.path.join(output_dir, "out", filename)
            with open(out_path, "w", encoding="utf-8") as out_f:
                out_f.write(result.stdout)

        return (
            input_file,
            score,
            relative_score,
            "AC",
            f"{(end_time-start_time):.3f}",
        )

    except subprocess.TimeoutExpired as e:
        with worker_lock:
            worker_counter.value += 1
            cnt = worker_counter.value
        if verbose:
            cnt_str = " " * (len(str(total_files)) - len(str(cnt))) + str(cnt)
            s = "-" * KETA_SCORE
            t = f">{timeout:.3f} sec"
            t = " " * (KETA_TIME - len(t)) + t
            logger.info(
                f"| {cnt_str} / {total_files} | {input_file} | {s} | {to_red(t)} |"
            )

        if record:
            with open(f"{output_dir}/err/{filename}", "w", encoding="utf-8") as out_f:
                stderr_val = (
                    e.stderr
                    if isinstance(e.stderr, str)
                    else (e.stderr.decode("utf-8", errors="ignore") if e.stderr else "")
                )
                out_f.write(stderr_val)
            with open(f"{output_dir}/out/{filename}", "w", encoding="utf-8") as out_f:
                stdout_val = (
                    e.stdout
                    if isinstance(e.stdout, str)
                    else (e.stdout.decode("utf-8", errors="ignore") if e.stdout else "")
                )
                out_f.write(stdout_val)

        return input_file, math.nan, math.nan, "TLE", f"{timeout:.3f}"

    except subprocess.CalledProcessError as e:
        with worker_lock:
            worker_counter.value += 1
        if record:
            with open(f"{output_dir}/err/{filename}", "w", encoding="utf-8") as out_f:
                if e.stderr is not None:
                    out_f.write(e.stderr)
            with open(f"{output_dir}/out/{filename}", "w", encoding="utf-8") as out_f:
                if e.stdout is not None:
                    out_f.write(e.stdout)
        logger.error(to_red(f"Error occured in {input_file}"))
        return input_file, math.nan, math.nan, "ERROR", "-1"

    except Exception as e:
        with worker_lock:
            worker_counter.value += 1
        logger.exception(e)
        logger.error(to_red(f"!!! Error occured in {input_file}"))
        return input_file, math.nan, math.nan, "INNER_ERROR", "-1"


class ParallelTester:

    def __init__(
        self,
        direction: str,
        filename: str,
        compile_command: str,
        execute_command: str,
        input_file_names: list[str],
        cpu_count: int,
        verbose: bool,
        get_score: Callable[[list[Optional[float]]], float],
        timeout: float,
        use_relative_score: bool,
        pre_dir_name: str,
    ) -> None:
        """
        Args:
            direction (str): 最小化か最大化を決定します(色がつきます)。
            compile_command (str): コンパイルコマンドです。
            execute_command (str): 実行コマンドです。
                                    実行時引数は ``append_execute_command()`` メソッドで指定することも可能です。
            input_file_names (list[str]): 入力ファイル名のリストです。
            cpu_count (int): CPU数です。
            verbose (bool): ログを表示します。
            get_score (Callable[[list[float]], float]): スコアのリストに対して平均などを取って返してください。
            timeout (float): [ms]
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
        self.added_command = []
        self.input_file_names = input_file_names
        self.cpu_count = cpu_count
        self.verbose = verbose
        self.get_score = get_score
        self.timeout = (
            timeout / 1000 if (timeout is not None) and (timeout >= 0) else None
        )
        self.use_relative_score = use_relative_score
        pre_dir_name = os.path.join(
            *["ahclib_results", "all_tests", pre_dir_name, "result.csv"]
        )
        self.pre_data = {}
        if os.path.exists(pre_dir_name):
            df = pd.read_csv(pre_dir_name)
            self.pre_data = dict(zip(df["filename"], df["score"]))

        self.rnd = Random(None)

    def show_score(self, scores: list[float]) -> float:
        """スコアのリストを受け取り、 ``get_score`` 関数で計算します。
        ついでに表示もします。
        """
        score = self.get_score(scores)
        logger.info(f"Ave.{score}")
        return score

    def append_execute_command(self, args: Iterable[str]) -> None:
        """コマンドライン引数を追加します。"""
        for arg in args:
            self.added_command.append(str(arg))

    def clear_execute_command(self) -> None:
        """これまでに追加したコマンドライン引数を削除します"""
        self.added_command.clear()

    def compile(self) -> None:
        """``compile_command`` よりコンパイルします。"""
        if self.compile_command is None:
            return
        subprocess.run(
            self.compile_command,
            capture_output=True,
            text=True,
            check=True,
        )

    def run_opt_wilcoxon(self, trial: optuna.trial.Trial) -> list[Optional[float]]:
        scores_list: list[float] = [None] * len(self.input_file_names)
        input_filenames = list(enumerate(self.input_file_names))
        self.rnd.shuffle(input_filenames)

        cmd = self.execute_command + self.added_command
        args_list = [
            (file, id_, cmd, self.timeout, self.use_relative_score, self.pre_data)
            for id_, file in input_filenames
        ]

        max_workers = max(1, self.cpu_count)
        args_iter = iter(args_list)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for _ in range(max_workers):
                try:
                    args = next(args_iter)
                except StopIteration:
                    break
                futures[executor.submit(worker_process_file_opt_wilcoxon, args)] = args

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
                        for pending in futures:
                            pending.cancel()
                        return scores_list
                    try:
                        args = next(args_iter)
                    except StopIteration:
                        continue
                    futures[executor.submit(worker_process_file_opt_wilcoxon, args)] = (
                        args
                    )
        return scores_list

    def run(self) -> list[float]:
        """実行します。"""
        cmd = self.execute_command + self.added_command
        args_list = [
            (file, cmd, self.timeout, self.use_relative_score, self.pre_data)
            for file in self.input_file_names
        ]

        max_workers = max(1, self.cpu_count)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            result = list(executor.map(worker_process_file_light, args_list))

        return result

    def run_record(self, record: bool):
        """実行します。"""
        dt_now = datetime.datetime.now()

        self.output_dir = "./ahclib_results/"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.output_dir += "all_tests/"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        self.output_dir += dt_now.strftime("%Y-%m-%d_%H-%M-%S")
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        src_basename = os.path.basename(self.filename)
        try:
            shutil.copy2(self.filename, os.path.join(self.output_dir, src_basename))
        except Exception as e:
            logger.warning(f"Failed to copy source file {self.filename}: {e}")
        try:
            shutil.copy2(
                "ahc_settings.py", os.path.join(self.output_dir, "ahc_settings.py")
            )
        except Exception as e:
            logger.warning(f"Failed to copy ahc_settings.py: {e}")

        if record:
            if not os.path.exists(f"{self.output_dir}/err/"):
                os.makedirs(f"{self.output_dir}/err/")
            if not os.path.exists(f"{self.output_dir}/out/"):
                os.makedirs(f"{self.output_dir}/out/")

        cmd = self.execute_command + self.added_command
        total_files = len(self.input_file_names)
        args_list = [
            (
                file,
                cmd,
                self.timeout,
                self.use_relative_score,
                self.pre_data,
                self.verbose,
                self.direction,
                self.output_dir,
                record,
                total_files,
            )
            for file in self.input_file_names
        ]

        init_worker(
            threading.Lock(),
            SimpleNamespace(value=0),
            SimpleNamespace(value=0.0),
            SimpleNamespace(value=0),
            SimpleNamespace(value=0.0),
            SimpleNamespace(value=0),
            SimpleNamespace(value=0),
            SimpleNamespace(value=0),
            SimpleNamespace(value=0),
        )
        max_workers = max(1, self.cpu_count)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            result = list(executor.map(worker_process_file, args_list))

        # csv
        result.sort()
        with open(
            f"{self.output_dir}/result.csv", "w", encoding="utf-8", newline=""
        ) as f:
            writer = csv.writer(f)
            if self.use_relative_score:
                writer.writerow(["filename", "score", "rel_score", "state", "time"])
            else:
                writer.writerow(["filename", "score", "state", "time"])
            for filename, score, rel_score, state, t in result:
                if self.use_relative_score:
                    writer.writerow([filename, score, rel_score, state, t])
                else:
                    writer.writerow([filename, score, state, t])

        if record:
            # 出力を`./out/`へも書き出す
            if not os.path.exists("./out/"):
                os.makedirs("./out/")
            for item in os.listdir(f"{self.output_dir}/out/"):
                src_path = os.path.join(f"{self.output_dir}/out/", item)
                dest_path = os.path.join("./out/", item)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dest_path)
                elif os.path.isdir(src_path):
                    shutil.copytree(src_path, dest_path)

        return result

    @staticmethod
    def get_args() -> argparse.Namespace:
        """実行時引数を解析します。"""
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
    """`ParallelTester` を返します

    Args:
        settings (AHCSettings):
        verbose (bool, optional): ログを表示します。

    Returns:
        ParallelTester: テスターです。
    """
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
    )
    return tester


def run_test(
    settings: AHCSettings,
    njobs: int,
    verbose: bool = False,
    compile: bool = False,
    record: bool = True,
) -> None:
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    njobs = max(1, min(njobs, multiprocessing.cpu_count() - 1))

    if verbose:
        logger.info(f"--- {to_bold('[Settings]')} ---")
        logger.info(f"direction       : {settings.direction}")
        logger.info(f"timeout         : {settings.timeout}")
        logger.info(f"filename        : {to_bold(to_blue((settings.filename)))}")
        if settings.use_relative_score:
            logger.info(f"pre_dir_name    : {settings.pre_dir_name}")
        logger.info(f"execute_command : {settings.execute_command}")
        logger.info(f"njobs           : {njobs}")
        logger.info("----------------")

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
        relative_scores = [r for _, _, r, _, _ in scores]
        if relative_scores.count(-1):
            logger.error(
                to_red(f"RelativeScore::ErrorCount: {relative_scores.count(-1)}.")
            )
        relative_scores = list(filter(lambda x: not math.isnan(x), relative_scores))
        less_cnt, same_cnt, uppe_cnt = 0, 0, 0
        log_sum = 0
        for r in relative_scores:
            if r == -1:
                continue
            log_sum += math.log(r)
            if r < 1.0:
                less_cnt += 1
            elif r == 1.0:
                same_cnt += 1
            else:
                uppe_cnt += 1
        if less_cnt + same_cnt + uppe_cnt != 0:
            ave_relative_score = math.exp(log_sum / (less_cnt + same_cnt + uppe_cnt))
            if settings.direction == "minimize":
                ave_relative_score = (
                    f"{ave_relative_score:.4f}"
                    if ave_relative_score == 1
                    else (
                        to_green(f"{ave_relative_score:.4f}")
                        if ave_relative_score < 1
                        else to_red(f"{ave_relative_score:.4f}")
                    )
                )
            else:
                ave_relative_score = (
                    f"{ave_relative_score:.4f}"
                    if ave_relative_score == 1
                    else (
                        to_green(f"{ave_relative_score:.4f}")
                        if ave_relative_score > 1
                        else to_red(f"{ave_relative_score:.4f}")
                    )
                )
        else:
            ave_relative_score = to_red("nan")

        less_cnt = (
            to_green(less_cnt) if settings.direction == "minimize" else to_red(less_cnt)
        )
        uppe_cnt = (
            to_red(uppe_cnt) if settings.direction == "minimize" else to_green(uppe_cnt)
        )
        logger.info(f"LESS : {less_cnt}.")
        logger.info(f"SAME : {same_cnt}.")
        logger.info(f"UPPER: {uppe_cnt}.")
        logger.info(f"RelativeScore: {ave_relative_score}.")

    nan_case = []
    for filename, s, _, state, _ in scores:
        if math.isnan(s):
            nan_case.append((filename, state))
    if nan_case:
        tle_cnt = 0
        other_cnt = 0
        inner_cnt = 0

        delta = max(13, max([len(filename) for filename, _ in nan_case])) + 2

        logger.error("=" * (delta + 2))
        logger.error(to_red(f"ErrorCount: {len(nan_case)}."))

        logger.error("-" * (delta + 2))
        logger.error("| TLE " + " " * (delta - len(" TLE ")) + "|")
        for f, state in nan_case:
            if state == "TLE":
                tle_cnt += 1
                logger.error("|" + to_red(f" {f} ") + "|")

        logger.error("-" * (delta + 2))

        logger.error("| ERROR " + " " * (delta - len(" ERROR ")) + "|")
        for f, state in nan_case:
            if state == "ERROR":
                other_cnt += 1
                logger.error("|" + to_red(f" {f} ") + "|")

        logger.error("-" * (delta + 2))

        logger.error("| INNER_ERROR " + " " * (delta - len(" INNER_ERROR ")) + "|")
        for f, state in nan_case:
            if state == "INNER_ERROR":
                inner_cnt += 1
                logger.error("|" + to_red(f" {f} ") + "|")

        logger.error("-" * (delta + 2))
        logger.error("=" * (delta + 2))

        logger.error(to_red(f" TLE   : {tle_cnt} "))
        logger.error(to_red(f" Other : {other_cnt} "))
        logger.error(to_red(f" Inner : {inner_cnt} "))

    score = tester.show_score([s for _, s, _, _, _ in scores])
    logger.info(to_green(f"Finished in {time.time() - start:.4f} sec."))
    return score


def main():
    """実行時引数をもとに、 ``tester`` を立ち上げ実行します。"""
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
