from parallel_tester import ParallelTester, build_tester
from optimizer import Optimizer
import sys
import importlib.util
import argparse

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
        "-c",
        "--config",
        required=False,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        required=False,
        default=False,
    )

    args_from_sys = sys.argv
    
    
    args = parser.parse_args()

    file_path = 'path/to/your/module.py'
    class_name = 'YourClass'
    cls = load_class_from_path(file_path, class_name)

    if args.command == "setup":
        print("setup")
    elif args.command == "test":
        tester = build_tester()
        print("test")
    elif args.command == "opt":
        print("opt")
    else:
        raise ValueError
