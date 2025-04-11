import optuna
from typing import Optional, Callable
from ahclib.ahc_util import avg_score, geo_score


"""example
python3 -m ahclib test -v -c -r
python3 -m opt -w

g++ ./main.cpp -O2 -std=c++20 -o a.out -I./../../../Library_cpp -march=native
"""


class AHCSettings:

    # parallel_tester -------------------- #
    direction = "minimize"  # minimize / maximize

    njobs = 100

    filename = "./main.cpp"
    compile_command = (
        "g++ ./main.cpp -O2 -std=c++20 -o a.out -I./../../../Library_cpp -march=native"
    )
    execute_command = "./a.out"
    input_file_names = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]

    timeout = None

    use_relative_score = False
    pre_dir_name = ""

    def get_score(scores: list[Optional[float]]) -> float:
        # assert None not in scores
        # return avg_score(scores)
        # return geo_score(socres)
        scores = list(filter(lambda x: x is not None, scores))
        return sum(scores) / len(scores)

    # ------------------------------------ #

    # optimizer -------------------------- #
    # study_name
    study_name = "test"

    # optuna の試行回数
    n_trials = 100

    # optuna の cpu_count
    njobs_optuna = 1

    def objective(trial: optuna.trial.Trial) -> tuple:
        # 返り値のタプルはコマンドライン引数として渡す順番にする
        start_temp = trial.suggest_float("start_temp", 1, 100, log=True)
        k = trial.suggest_float("k", 0.0001, 1, log=True)
        end_temp = start_temp * k
        return (start_temp, end_temp)

    # ------------------------------------ #
