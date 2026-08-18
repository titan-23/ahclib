import argparse
import importlib.util
import os
import shutil
import sys
from typing import Any, Optional, Sequence

import click

from .ahc_util import to_blue, to_bold


def load_class_from_path(
    file_path: str,
    class_name: Optional[str] = None,
) -> Any:
    """指定した Python ファイルを読み、モジュールまたは指定クラスを返す"""
    module_name = file_path.replace("/", ".").replace("\\", ".").split(".")[0]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if class_name:
        return getattr(module, class_name)
    return module


def _add_settings_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-s",
        "--settings",
        required=False,
        default="ahc_settings.py",
    )


def _port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port は 1 から 65535 で指定してください")
    return port


def get_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup")
    vis_parser = subparsers.add_parser("vis")
    vis_parser.add_argument(
        "--tailscale",
        action="store_true",
        help="vis を Tailscale の tailnet 内へ読み取り専用で共有する",
    )
    vis_parser.add_argument(
        "--port",
        type=_port_number,
        default=8050,
        help="vis が使うローカル port (既定: 8050)",
    )
    subparsers.add_parser("clear")

    test_parser = subparsers.add_parser("test")
    _add_settings_argument(test_parser)
    test_parser.add_argument(
        "--compile",
        default=True,
        action=argparse.BooleanOptionalAction,
    )
    test_parser.add_argument(
        "--verbose",
        default=True,
        action=argparse.BooleanOptionalAction,
    )
    test_parser.add_argument(
        "--record",
        default=True,
        action=argparse.BooleanOptionalAction,
    )
    test_parser.add_argument(
        "-m",
        "--memo",
        required=False,
        default=None,
        help="test の実行結果に添えるメモ (結果ディレクトリの memo.txt に保存され vis に表示される)",
    )

    beam_parser = subparsers.add_parser("vis_beam")
    beam_parser.add_argument(
        "--history",
        required=False,
        default="history.json",
        help="vis_beam で読み込む history.json のパス",
    )
    beam_parser.add_argument(
        "--vis",
        "--visualizer",
        dest="visualizer",
        required=False,
        default=None,
        help="vis_beam で使う visualizer.py のパス (省略時は ./visualizer.py を自動検出)",
    )

    opt_parser = subparsers.add_parser("opt")
    _add_settings_argument(opt_parser)
    opt_parser.add_argument(
        "--vis",
        action="store_true",
        help="最適化を行わず、保存済み study の Optuna Dashboard だけを起動する",
    )
    opt_parser.add_argument(
        "--tailscale",
        action="store_true",
        help="Optuna Dashboard を Tailscale の tailnet 内だけに共有する",
    )
    opt_parser.add_argument(
        "--wilcoxon",
        default=True,
        action=argparse.BooleanOptionalAction,
    )
    opt_parser.add_argument(
        "-a",
        "--auto_sampler",
        required=False,
        default=False,
        action="store_true",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = get_args()

    if args.command == "vis":
        from .vis import run_vis

        run_vis(tailscale=args.tailscale, port=args.port)
        sys.exit(0)

    if args.command == "vis_beam":
        from .beam.app import create_app
        from .beam.default_visualizer import generate_board_visual as _default_vis

        visualizer_path = args.visualizer or os.path.join(os.getcwd(), "visualizer.py")
        if os.path.exists(visualizer_path):
            visualizer_module = load_class_from_path(visualizer_path)
            generate_board_visual = getattr(
                visualizer_module, "generate_board_visual", _default_vis
            )
        else:
            generate_board_visual = _default_vis

        beam_app = create_app(generate_board_visual, history_path=args.history)
        beam_app.run(debug=False)
        sys.exit(0)

    if args.command == "opt" and args.vis:
        from .optimizer import run_optimizer_dashboard

        run_optimizer_dashboard(tailscale=args.tailscale)
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
        except Exception as error:
            print(f"Error: {error}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.command == "clear":
        print("clear", file=sys.stderr)
        if click.confirm("Delete the directory ./ahclib_results/?"):
            try:
                shutil.rmtree("./ahclib_results/")
            except Exception as error:
                print(f"Error occurred: {error}", file=sys.stderr)
            else:
                print("Directory removed successfully.", file=sys.stderr)
        else:
            print("Deletion cancelled.", file=sys.stderr)
        sys.exit(0)

    file_path = args.settings
    class_name = "AHCSettings"
    settings = load_class_from_path(file_path, class_name)

    if args.command == "test":
        from .parallel_tester import run_test

        run_test(
            settings,
            settings.njobs,
            args.verbose,
            args.compile,
            args.record,
            args.memo,
        )
    elif args.command == "opt":
        from .optimizer import run_optimizer

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
        run_optimizer(settings, sampler, pruner, tailscale=args.tailscale)
    else:
        raise ValueError
