from .parallel_tester import run_test
from .optimizer import run_optimizer, run_optimizer_wilcoxon
import sys
import importlib.util
import argparse
import shutil
from logging import basicConfig
import os


def load_class_from_path(file_path, class_name=None):
    module_name = file_path.replace("/", ".").replace("\\", ".").split(".")[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if class_name:
        return getattr(module, class_name)
    return module


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["setup", "test", "opt"],
        help="",
    )
    parser.add_argument(
        "-s",
        "--settings",
        required=False,
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

    args = parser.parse_args()
    if args.command == "setup":
        print("setup")
        module_dir = os.path.dirname(os.path.abspath(__file__))
        source_file = os.path.join(module_dir, "ahc_settings.py")
        caller_dir = os.getcwd()
        destination_file = os.path.join(caller_dir, "ahc_settings.py")
        try:
            shutil.copy(source_file, destination_file)
            print(f"Copied {source_file} to {destination_file}")
        except FileNotFoundError:
            print(f"Error: {source_file} does not exist.")
            sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

        exit()

    file_path = "ahc_settings.py"
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
        if args.wilcoxon:
            raise NotImplementedError
            run_optimizer_wilcoxon(settings)
        else:
            run_optimizer(settings)
    else:
        raise ValueError
