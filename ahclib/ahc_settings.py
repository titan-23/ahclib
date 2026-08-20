import sys
from typing import Any, Optional

import optuna

from ahclib.ahc_util import avg_score, geo_score, to_red

"""設定例

python3 -m ahclib test
python3 -m ahclib opt  # 標準では WilcoxonPruner を使用する
"""


class AHCSettings:
    # 並列テスト
    direction: str = "maximize"  # minimize / maximize
    njobs: int = 100
    cpu_affinity: bool = True  # Linux / WSL でケースごとに logical CPU を固定する
    timeout: Optional[int] = None
    is_int: bool = True  # 整数スコアなら True、小数スコアなら False

    filename: str = "./main.cpp"
    compile_command: Optional[str] = (
        f"g++ {filename} -O2 -DLOCAL -std=c++20 -o a.out " "-fopenmp -I. -I./../../Library_cpp -march=native"
    )
    execute_command: str = "./a.out"
    input_file_names: list[str] = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]

    use_relative_score: bool = False
    pre_dir_name: str = ""

    @staticmethod
    def get_score(scores: list[Optional[float]]) -> float:
        # return avg_score(scores)
        # return geo_score(scores)
        valid_scores = [score for score in scores if score is not None]
        return sum(valid_scores) / len(valid_scores)

    # Optuna
    study_name: str = "test"
    optuna_seed: Optional[int] = 23

    n_trials: int = 50
    optuna_timeout: Optional[float] = None  # 分単位で None なら時間制限なし

    # study.optimize を独立して実行するプロセス数
    njobs_optuna: int = 1

    @staticmethod
    def objective(trial: optuna.trial.Trial) -> tuple[float, ...]:
        # 戻り値はソルバーへ渡すコマンドライン引数の順番に並べる

        # 焼きなましの温度
        start_temp = trial.suggest_float("start_temp", 1e0, 1e5, log=True)
        k = trial.suggest_float("k", 1e-6, 1, log=True)

        # 焼きなましの重み
        weights = [
            1.0,
            trial.suggest_float("w1", 1e-2, 1e2, log=True),
            trial.suggest_float("w2", 1e-2, 1e2, log=True),
        ]
        total_weight = sum(weights)
        normalized_weights = [weight / total_weight for weight in weights]
        return (start_temp, k, *normalized_weights)

    # 探索開始時に評価するパラメータの組
    optuna_init_trials: list[dict[str, int | float]] = [
        # {"start_temp": 1000.0, "k": 0.01, "w1": 1.0, "w2": 1.0,},
    ]

    # TPE がランダム探索を行う最初の trial 数
    optuna_n_startup_trials: int = 10

    # テスト結果の可視化

    @staticmethod
    def parse_input_params(file_path: str) -> dict[str, Any]:
        """入力ファイルを読み、可視化に使うパラメータを返す"""
        try:
            with open(file_path, "r", encoding="utf-8") as input_file:
                lines = input_file.readlines()
            parameters: dict[str, Any] = {}
            # 例: parameters["N"], parameters["M"] = map(int, lines[0].split())
            return parameters
        except Exception:
            print(to_red("[Error] : failed in parse_input_params"), file=sys.stderr)
            return {}

    # ビームサーチの可視化
    vis_beam_input: str = ""
