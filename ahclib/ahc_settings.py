import optuna
import sys
from typing import Optional, Callable
from ahclib.ahc_util import avg_score, geo_score, to_red

"""example
python3 -m ahclib test
python3 -m opt
"""


class AHCSettings:

    # parallel_tester -------------------- #
    direction = "maximize"  # minimize / maximize
    njobs = 100
    timeout = None

    filename = "./main.cpp"
    compile_command = f"g++ {filename} -O2 -DLOCAL -std=c++20 -o a.out -fopenmp -I. -I./../../Library_cpp -march=native"
    execute_command = "./a.out"
    input_file_names = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]

    use_relative_score = False
    pre_dir_name = ""

    @staticmethod
    def get_score(scores: list[Optional[float]]) -> float:
        # assert None not in scores
        # return avg_score(scores)
        # return geo_score(socres)
        scores = list(filter(lambda x: x is not None, scores))
        return sum(scores) / len(scores)

    # optimizer -------------------------- #
    # study_name
    study_name = "test"

    # optuna の試行回数
    n_trials = 50

    # optuna の cpu_count
    # HINT: wilcoxonで枝刈りが行われるので、njobsをある程度小さくしてnjobs_optunaを数個にするとよさそう
    njobs_optuna = 1

    @staticmethod
    def objective(trial: optuna.trial.Trial) -> tuple:
        # 返り値のタプルはコマンドライン引数として渡す順番にする
        start_temp = trial.suggest_float("start_temp", 1e0, 1e5, log=True)
        k = trial.suggest_float("k", 1e-6, 1, log=True)
        return (start_temp, k)

    # 探索の起点として最初に評価するパラメータ値のリストを指定する
    optuna_init_trials = [
        # {"start_temp": 1000.0, "k": 0.01},
    ]

    # (TPE)ランダムに探索する試行回数を指定する
    optuna_n_startup_trials = 10  # デフォルト

    # visualize -------------------------- #

    @staticmethod
    def parse_input_params(file_path: str) -> dict:
        """./in/ 以下のファイルを読み込み、パラメータを辞書で返す"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            res = {}
            # TODO
            # res["N"], res["M"] = map(int, lines[0].split())
            return res
        except Exception:
            print(to_red("[Error] : failed in parse_input_params"), file=sys.stderr)
            return {}

    # vis_beam ---------------------------------- #

    vis_beam_input = ""
