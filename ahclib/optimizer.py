import optuna
import time
from logging import getLogger, basicConfig
import os
import subprocess
import multiprocessing
from .parallel_tester import ParallelTester, build_tester
from .ahc_settings import AHCSettings
from .ahc_util import to_blue, to_bold
# import optunahub

logger = getLogger(__name__)


class Optimizer:

    def __init__(self, settings: AHCSettings) -> None:
        self.settings: AHCSettings = settings
        self.study_name = settings.study_name
        self.path = f"./ahclib_results/optimizer_results"
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def optimize_wilcoxon(self) -> None:
        raise NotImplementedError
        tester: ParallelTester = build_tester(
            self.settings, njobs=self.settings.njobs, verbose=False
        )
        tester.compile()
        start = time.time()

        study: optuna.Study = optuna.create_study(
            direction=self.settings.direction,
            study_name=self.settings.study_name,
            storage=f"sqlite:///{self.path}/{self.settings.study_name}.db",
            load_if_exists=True,
            pruner=optuna.pruners.WilcoxonPruner(p_threshold=0.1),
        )

        def _objective(trial: optuna.trial.Trial) -> float:
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            args = self.settings.objective(trial)
            tester.append_execute_command(args)
            scores, state = tester.run_opt_wilcoxon(trial)
            if not state:
                print("Pruned!")
                raise optuna.TrialPruned()
            score = tester.get_score(scores)
            return score

        study.optimize(
            _objective,
            n_trials=self.settings.n_trials,
            n_jobs=min(self.settings.njobs_optuna, multiprocessing.cpu_count() - 1),
        )

        logger.info(study.best_trial)
        logger.info("writing results ...")
        self.output_study(study)
        logger.info(f"Finish parameter seraching. Time: {time.time() - start:.2f}sec.")

    def optimize(self) -> None:
        logger.info(f"==============================================")
        logger.info(to_bold(to_blue(f"Optimizer settings:")))
        logger.info(f"- study_name    : {to_bold(self.settings.study_name)}")
        logger.info(f"- direction     : {to_bold(self.settings.direction)}")
        logger.info(f"- n_trials      : {to_bold(self.settings.n_trials)}")

        start = time.time()

        tester: ParallelTester = build_tester(
            self.settings,
            njobs=self.settings.njobs,
            verbose=False,
        )

        def _objective(trial: optuna.trial.Trial) -> float:
            args = self.settings.objective(trial)
            tester.clear_execute_command()
            tester.append_execute_command(args)
            scores = tester.run()
            score = tester.get_score(scores)
            return score

        storage = f"sqlite:///{self.path}/data.db"
        study: optuna.Study = optuna.create_study(
            direction=self.settings.direction,
            study_name=self.settings.study_name,
            storage=storage,
            load_if_exists=True,
            # sampler=optunahub.load_module("samplers/auto_sampler").AutoSampler(),
        )

        try:
            logger.info(f"------------------------------------------")
            process = subprocess.Popen(
                ["optuna-dashboard", storage],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            dashboard_url = None
            for line in iter(process.stderr.readline, ""):
                if line.startswith("Listening on "):
                    dashboard_url = line.split("Listening on")[-1].strip()
                    break
            if dashboard_url:
                logger.info(f"- dashboard URL : {to_bold(dashboard_url)}")
            else:
                logger.error("Dashboard URL could not be determined.")
                exit(1)
            logger.info(f"==============================================")

            tester.compile()
            study.optimize(
                _objective,
                n_trials=self.settings.n_trials,
                n_jobs=min(self.settings.njobs_optuna, multiprocessing.cpu_count() - 1),
            )

            logger.info(study.best_trial)
            logger.info("writing results ...")
            self.output_study(study)
            logger.info(
                f"Finish parameter seraching. Time: {time.time() - start:.2f}sec."
            )
        except Exception as e:
            print(e)
            exit(1)
        process.terminate()
        process.wait()

    def output_study(self, study: optuna.Study) -> None:
        path = os.path.join(self.path, self.study_name)
        if not os.path.exists(path):
            os.makedirs(path)
        with open(f"{path}/result.txt", "w", encoding="utf-8") as f:
            print(study.best_trial, file=f)

        img_path = os.path.join(path, "images")
        if not os.path.exists(img_path):
            os.makedirs(img_path)

        fig = optuna.visualization.plot_contour(study)
        fig.write_html(os.path.join(img_path, "contour.html"))
        fig.write_image(os.path.join(img_path, "contour.png"))

        fig = optuna.visualization.plot_param_importances(study)
        fig.write_html(os.path.join(img_path, "param_importances.html"))
        fig.write_image(os.path.join(img_path, "param_importances.png"))

        fig = optuna.visualization.plot_edf(study)
        fig.write_html(os.path.join(img_path, "edf.html"))
        fig.write_image(os.path.join(img_path, "edf.png"))

        fig = optuna.visualization.plot_optimization_history(study)
        fig.write_html(os.path.join(img_path, "optimization_history.html"))
        fig.write_image(os.path.join(img_path, "optimization_history.png"))

        fig = optuna.visualization.plot_parallel_coordinate(study)
        fig.write_html(os.path.join(img_path, "parallel_coordinate.html"))
        fig.write_image(os.path.join(img_path, "parallel_coordinate.png"))

        fig = optuna.visualization.plot_slice(study)
        fig.write_html(os.path.join(img_path, "slice.html"))
        fig.write_image(os.path.join(img_path, "slice.png"))


def run_optimizer(settings: AHCSettings):
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    optimizer: Optimizer = Optimizer(settings)
    optimizer.optimize()


def run_optimizer_wilcoxon(settings: AHCSettings):
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )

    optimizer: Optimizer = Optimizer(settings)
    optimizer.optimize_wilcoxon()


if __name__ == "__main__":
    run_optimizer(AHCSettings)
