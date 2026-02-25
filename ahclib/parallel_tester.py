import multiprocessing.managers
from typing import Iterable, Callable, Optional
import argparse
from logging import getLogger, basicConfig
import subprocess
import multiprocessing
import time
import math
import os
from random import Random
import shutil
import sys
import csv
import optuna
import datetime
import pandas as pd
from .ahc_settings import AHCSettings
from .ahc_util import to_green, to_red

logger = getLogger(__name__)

KETA_SCORE = 10
KETA_TIME = 11
KETA_REL_SCORE = 10

worker_lock = None
worker_counter = None

def init_worker(lock, counter):
    """各ワーカープロセスの初期化時に呼ばれ、LockとCounterをセットします。"""
    global worker_lock, worker_counter
    worker_lock = lock
    worker_counter = counter


def worker_process_file_opt_wilcoxon(args) -> tuple[int, float]:
    input_file, id_, cmd, timeout, use_relative_score, pre_data = args
    with open(input_file, "r", encoding="utf-8") as f:
        input_text = f.read()
    try:
        result = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
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
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
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
    (input_file, cmd, timeout, use_relative_score, pre_data,
     verbose, direction, output_dir, record, total_files) = args

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
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        )
        end_time = time.perf_counter()
        score_line = result.stderr.rstrip().split("\n")[-1]
        _, score = score_line.split(" = ")
        score = float(score)

        relative_score = (
            -1
            if input_file not in pre_data
            else score / pre_data[input_file]
        )

        if verbose:
            with worker_lock:
                worker_counter.value += 1
                cnt = worker_counter.value

            cnt_str = " " * (len(str(total_files)) - len(str(cnt))) + str(cnt)
            s = str(f"{score:.3f}")
            s = " " * (KETA_SCORE - len(s)) + s
            t = f"{(end_time-start_time):.3f} sec"
            t = " " * (KETA_TIME - len(t)) + t

            u = ""
            if direction == "minimize":
                u = (
                    to_green(f"{(relative_score):.3f}")
                    if relative_score < 1.0
                    else to_red(f"{(relative_score):.3f}")
                )
            else:
                u = (
                    to_green(f"{(relative_score):.3f}")
                    if relative_score > 1.0
                    else to_red(f"{(relative_score):.3f}")
                )

            if use_relative_score:
                logger.info(
                    f"| {cnt_str} / {total_files} | {input_file} | {s} | {t} | {u} |"
                )
            else:
                logger.info(
                    f"| {cnt_str} / {total_files} | {input_file} | {s} | {t} |"
                )

        if record:
            with open(f"{output_dir}/err/{filename}", "w", encoding="utf-8") as out_f:
                out_f.write(result.stderr)
            with open(f"{output_dir}/out/{filename}", "w", encoding="utf-8") as out_f:
                out_f.write(result.stdout)

        return (
            input_file,
            score,
            relative_score,
            "AC",
            f"{(end_time-start_time):.3f}",
        )

    except subprocess.TimeoutExpired as e:
        if verbose:
            with worker_lock:
                worker_counter.value += 1
                cnt = worker_counter.value
            cnt_str = " " * (len(str(total_files)) - len(str(cnt))) + str(cnt)
            s = "-" * KETA_SCORE
            t = f">{timeout:.3f} sec"
            t = " " * (KETA_TIME - len(t)) + t
            logger.info(
                f"| {cnt_str} / {total_files} | {input_file} | {s} | {to_red(t)} |"
            )

        if record:
            with open(f"{output_dir}/err/{filename}", "w", encoding="utf-8") as out_f:
                stderr_val = e.stderr if isinstance(e.stderr, str) else (e.stderr.decode("utf-8", errors="ignore") if e.stderr else "")
                out_f.write(stderr_val)
            with open(f"{output_dir}/out/{filename}", "w", encoding="utf-8") as out_f:
                stdout_val = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode("utf-8", errors="ignore") if e.stdout else "")
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
            for _, row in df.iterrows():
                self.pre_data[row["filename"]] = row["score"]

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
        logger.info("Compiling ...")
        subprocess.run(
            self.compile_command,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
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

        with multiprocessing.Pool(processes=self.cpu_count) as pool:
            result_iterator = pool.imap_unordered(
                worker_process_file_opt_wilcoxon,
                args_list,
                chunksize=1,
            )
            for id_, score in result_iterator:
                trial.report(score, id_)
                scores_list[id_] = score
                if trial.should_prune():
                    break
        return scores_list

    def run(self) -> list[float]:
        """実行します。"""
        cmd = self.execute_command + self.added_command
        args_list = [
            (file, cmd, self.timeout, self.use_relative_score, self.pre_data)
            for file in self.input_file_names
        ]

        with multiprocessing.Pool(processes=self.cpu_count) as pool:
            result = pool.map(worker_process_file_light, args_list, chunksize=1)

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
        with open(
            os.path.join(self.output_dir, self.filename), "w", encoding="utf-8"
        ) as outs:
            with open(self.filename, "r", encoding="utf-8") as inps:
                for line in inps:
                    outs.write(line)

        if record:
            if not os.path.exists(f"{self.output_dir}/err/"):
                os.makedirs(f"{self.output_dir}/err/")
            if not os.path.exists(f"{self.output_dir}/out/"):
                os.makedirs(f"{self.output_dir}/out/")

        cmd = self.execute_command + self.added_command
        total_files = len(self.input_file_names)
        args_list = [
            (file, cmd, self.timeout, self.use_relative_score, self.pre_data,
             self.verbose, self.direction, self.output_dir, record, total_files)
            for file in self.input_file_names
        ]

        with multiprocessing.Manager() as manager:
            lock = manager.Lock()
            counter = manager.Value("i", 0)

            with multiprocessing.Pool(
                processes=self.cpu_count,
                initializer=init_worker,
                initargs=(lock, counter)
            ) as pool:
                result = pool.map(
                    worker_process_file,
                    args_list,
                    chunksize=1,
                )

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

    tester = build_tester(settings, njobs, verbose)
    logger.info(f"{njobs=}")

    if compile:
        tester.compile()

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
        less_cnt, uppe_cnt = 0, 0
        log_sum = 0
        for r in relative_scores:
            if r == -1:
                continue
            log_sum += math.log(r)
            if r < 1.0:
                less_cnt += 1
            else:
                uppe_cnt += 1
        if less_cnt + uppe_cnt != 0:
            ave_relative_score = math.exp(log_sum / (less_cnt + uppe_cnt))
            if settings.direction == "minimize":
                ave_relative_score = (
                    to_green(f"{ave_relative_score:.4f}")
                    if ave_relative_score < 1
                    else to_red(f"{ave_relative_score:.4f}")
                )
            else:
                ave_relative_score = (
                    to_green(f"{ave_relative_score:.4f}")
                    if ave_relative_score > 1
                    else to_red(f"{ave_relative_score:.4f}")
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
