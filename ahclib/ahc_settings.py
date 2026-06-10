import optuna
import sys
from typing import Optional, Any
from ahclib.ahc_util import avg_score, geo_score, to_red

"""example
python3 -m ahclib test
python3 -m opt  # デフォルトで WilcoxonPruner を採用
"""


class AHCSettings:

    # parallel_tester -------------------- #
    direction: str = "maximize"  # minimize / maximize
    njobs: int = 100
    timeout: Optional[int] = None
    is_int: bool = True  # スコアが整数なら True 小数なら False

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
    optuna_seed: Optional[int] = 23

    # optuna の試行回数
    n_trials = 50
    # optuna の実行時間制限 [min]
    optuna_timeout = None

    # optuna の cpu_count
    njobs_optuna = 1

    @staticmethod
    def objective(trial: optuna.trial.Trial) -> tuple:
        # 返り値のタプルはコマンドライン引数として渡す順番にする

        # 焼きなましの温度
        start_temp = trial.suggest_float("start_temp", 1e0, 1e5, log=True)
        k = trial.suggest_float("k", 1e-6, 1, log=True)

        # 焼きなましの重み付け
        W = [
            1.0,
            trial.suggest_float("w1", 1e-2, 1e2, log=True),
            trial.suggest_float("w2", 1e-2, 1e2, log=True),
        ]
        W = list(map(x / sum(W) for x in W))
        return (start_temp, k, *W)

    # 探索の起点として最初に評価するパラメータ値の辞書をリストを指定する
    optuna_init_trials: list[dict[str, int | float]] = [
        # {"start_temp": 1000.0, "k": 0.01, "w1": 1.0, "w2": 1.0,},
    ]

    # ランダムに探索する試行回数を指定する
    optuna_n_startup_trials = 10  # デフォルト

    # visualize -------------------------- #

    @staticmethod
    def parse_input_params(file_path: str) -> dict[str, Any]:
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
