from .parallel_tester import run_test
from .ahc_util import to_bold, to_blue
from .optimizer import run_optimizer
import sys
import importlib.util
import argparse
import shutil
from logging import basicConfig
import subprocess
import os
import click


def load_class_from_path(file_path, class_name=None):
    module_name = file_path.replace("/", ".").replace("\\", ".").split(".")[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if class_name:
        return getattr(module, class_name)
    return module


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["setup", "vis", "test", "opt", "clear"],
        help="",
    )
    parser.add_argument(
        "-s",
        "--settings",
        required=False,
        default="ahc_settings.py",
    )
    parser.add_argument(
        "-c",
        "--compile",
        required=False,
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        required=False,
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-r",
        "--record",
        required=False,
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-w",
        "--wilcoxon",
        required=False,
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-a",
        "--auto_sampler",
        required=False,
        default=False,
        action="store_true",
    )
    args = parser.parse_args()
    return args


def main():
    args = get_args()

    if args.command == "vis":
        from . import vis

        vis.app.run(debug=False)
        sys.exit(0)

    if args.command == "setup":
        print("setup", file=sys.stderr)
        module_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(module_dir, "ahc_settings.py")
        caller_dir = os.getcwd()
        destination_file = os.path.join(caller_dir, "ahc_settings.py")
        try:
            shutil.copy(source_file, destination_file)
            print(f"Copied {source_file} to {destination_file}", file=sys.stderr)
        except FileNotFoundError:
            print(f"Error: {source_file} does not exist.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.command == "clear":
        print("clear", file=sys.stderr)
        if click.confirm("Delete the directory ./ahclib_results/?"):
            try:
                shutil.rmtree("./ahclib_results/")
            except Exception as e:
                print(f"Error occurred: {e}", file=sys.stderr)
            else:
                print("Directory removed successfully.", file=sys.stderr)
        else:
            print("Deletion cancelled.", file=sys.stderr)
        sys.exit(0)

    file_path = args.settings
    class_name = "AHCSettings"
    settings = load_class_from_path(file_path, class_name)

    if args.command == "test":
        basicConfig(
            format="%(asctime)s [%(levelname)s] : %(message)s",
            datefmt="%H:%M:%S",
            level=os.getenv("LOG_LEVEL", "INFO"),
        )
        run_test(settings, settings.njobs, args.verbose, args.compile, args.record)
    elif args.command == "opt":
        sampler = None
        pruner = None
        if args.wilcoxon:
            print(to_bold(to_blue("wilcoxon option has been set.")), file=sys.stderr)
            pruner = "WilcoxonPruner"
        if args.auto_sampler:
            print(
                to_bold(to_blue("auto_sampler option has been set.")), file=sys.stderr
            )
            sampler = "auto_sampler"
        run_optimizer(settings, sampler, pruner)
    else:
        raise ValueError
