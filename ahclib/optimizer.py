import optuna
import time
from typing import Optional, Callable
from logging import getLogger, basicConfig
import os
import re
import subprocess
import multiprocessing
import psycopg2
from .parallel_tester import ParallelTester, build_tester
from .ahc_settings import AHCSettings
from .ahc_util import to_blue, to_bold, to_green
import optunahub

logger = getLogger(__name__)


class Optimizer:

    POSTGRES_DB_PREFIX = "ahclib_optuna_"
    POSTGRES_MAINTENANCE_DB = "postgres"

    def __init__(self, settings: AHCSettings) -> None:
        self.settings: AHCSettings = settings
        self.study_name = settings.study_name
        self.path = f"./ahclib_results/optimizer_results"
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def _postgres_db_name(self) -> str:
        normalized = re.sub(r"[^a-z0-9_]+", "_", self.study_name.lower()).strip("_")
        if not normalized:
            normalized = "study"
        return f"{self.POSTGRES_DB_PREFIX}{normalized}"

    @staticmethod
    def _quote_postgres_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def _ensure_postgres_database(self, db_name: str) -> None:
        conn = psycopg2.connect(dbname=self.POSTGRES_MAINTENANCE_DB)
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (db_name,),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        f"CREATE DATABASE {self._quote_postgres_identifier(db_name)}"
                    )
        finally:
            conn.close()

    def _build_storage_url(self) -> str:
        db_name = self._postgres_db_name()
        self._ensure_postgres_database(db_name)
        return f"postgresql+psycopg2:///{db_name}"

    def optimize(
        self, sampler: Optional[str] = None, pruner: Optional[str] = None
    ) -> None:
        logger.info(f"==============================================")
        logger.info(to_bold(to_blue(f"Optimizer settings:")))
        logger.info(f"- study_name    : {to_bold(self.settings.study_name)}")
        logger.info(f"- direction     : {to_bold(self.settings.direction)}")
        logger.info(f"- n_trials      : {to_bold(self.settings.n_trials)}")
        optuna_timeout_min = self.settings.optuna_timeout
        optuna_timeout = (
            optuna_timeout_min * 60 if optuna_timeout_min is not None else None
        )
        logger.info(f"- timeout [min] : {to_bold(optuna_timeout_min)}")

        start = time.time()

        def _objective(trial: optuna.trial.Trial) -> float:
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            args = self.settings.objective(trial)
            tester.append_execute_command(args)
            scores = tester.run()
            score = tester.get_score(scores)
            return score

        def _objective_wilcoxon_pruner(trial: optuna.trial.Trial) -> float:
            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            args = self.settings.objective(trial)
            tester.append_execute_command(args)
            scores = tester.run_opt_pruner(trial)
            if None in scores:
                tried_cnt = len(scores) - scores.count(None)
                logger.info(
                    to_green(
                        f"pruned ! | {str(tried_cnt).zfill(len(str(int(len(scores)))))} / {len(scores)}"
                    )
                )
                raise optuna.TrialPruned()
            score = tester.get_score(scores)
            return score

        storage_url = self._build_storage_url()
        storage = optuna.storages.RDBStorage(
            url=storage_url,
            heartbeat_interval=60,
            grace_period=120,
        )
        _objective_func: Callable[[optuna.trial.Trial], float] = _objective

        optuna_seed = self.settings.optuna_seed
        if sampler == "auto_sampler":
            optuna_sampler = optunahub.load_module(
                "samplers/auto_sampler"
            ).AutoSampler(seed=optuna_seed)
        else:
            sampler = "TPESampler"
            optuna_sampler = optuna.samplers.TPESampler(
                multivariate=True,
                n_startup_trials=self.settings.optuna_n_startup_trials,
                seed=optuna_seed,
            )
        logger.info(f"- sampler       : {to_bold(sampler)}")

        optuna_pruner = None
        if pruner == "WilcoxonPruner":
            logger.info(f"- pruner        : {to_bold(pruner)}")
            optuna_pruner = optuna.pruners.WilcoxonPruner(p_threshold=0.1)
            _objective_func = _objective_wilcoxon_pruner

        study: optuna.Study = optuna.create_study(
            direction=self.settings.direction,
            study_name=self.settings.study_name,
            storage=storage,
            load_if_exists=True,
            sampler=optuna_sampler,
            pruner=optuna_pruner,
        )

        for params in self.settings.optuna_init_trials:
            study.enqueue_trial(params)

        try:
            logger.info(f"------------------------------------------")
            process = subprocess.Popen(
                ["optuna-dashboard", storage_url],
                stdout=subprocess.DEVNULL,
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

            tester: ParallelTester = build_tester(
                self.settings,
                njobs=self.settings.njobs,
                verbose=False,
            )
            tester.compile()
            study.optimize(
                _objective_func,
                n_trials=self.settings.n_trials,
                timeout=optuna_timeout,
                n_jobs=min(self.settings.njobs_optuna, multiprocessing.cpu_count() - 1),
            )

            logger.info(study.best_trial)
            logger.info("writing results ...")
            self.output_study(study)
            logger.info(
                f"Finish parameter seraching. Time: {time.time() - start:.2f}sec."
            )
            input(to_bold(to_blue("Press Enter to close the dashboard and exit...")))

        except Exception:
            logger.exception("Optimizer failed.")
            exit(1)
        finally:
            if "process" in locals():
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

        def save_plot(fig, filename):
            fig.write_html(os.path.join(img_path, f"{filename}.html"))
            try:
                fig.write_image(os.path.join(img_path, f"{filename}.png"))
            except ValueError:
                pass

        save_plot(optuna.visualization.plot_contour(study), "contour")
        save_plot(
            optuna.visualization.plot_param_importances(study), "param_importances"
        )
        save_plot(optuna.visualization.plot_edf(study), "edf")
        save_plot(
            optuna.visualization.plot_optimization_history(study),
            "optimization_history",
        )
        save_plot(
            optuna.visualization.plot_parallel_coordinate(study), "parallel_coordinate"
        )
        save_plot(optuna.visualization.plot_slice(study), "slice")


def run_optimizer(settings: AHCSettings, sampler=None, pruner=None) -> None:
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    optimizer: Optimizer = Optimizer(settings)
    optimizer.optimize(sampler, pruner)


if __name__ == "__main__":
    run_optimizer(AHCSettings)
