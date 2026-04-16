# -*- coding: utf-8 -*-

# user settings --------------------------------------------------
# `./titan_cpplib` がある絶対パス
LIB_PATH = (
    "/mnt/c/Users/titan/source/Library_cpp/",
    "C:\\Users\\titan\\source\\Library_cpp\\",
    "/home/titan/source/Library_cpp/",
)
#  ---------------------------------------------------------------

from logging import getLogger, basicConfig
import os
import pyperclip
import shutil
import argparse

logger = getLogger(__name__)


def to_red(arg):
    return f"\u001b[31m{arg}\u001b[0m"


def to_green(arg):
    return f"\u001b[32m{arg}\u001b[0m"


class CppExpander:

    @staticmethod
    def init_clipboard():
        """pyperclipを日本語に対応させる"""
        for command in ["wl-clipboard", "xclip", "xsel"]:
            if shutil.which(command):
                pyperclip.set_clipboard(command)
                break

    def __init__(self) -> None:
        """`CppExpander`をインスタンス化する"""
        self.input_file_path: str = "None"
        self.outputs: list[str] = []
        self.added_file: set[str] = set()

    def expand(self, input_file_path: str, output_fie_path: str) -> None:
        """input_filepathのコードを展開してoutput_fiepathに書き出す

        Args:
            input_file_path (str): 入力ファイル
            output_fie_path (str): 出力ファイル / `clip`のとき、クリップボードに貼り付ける
        """
        if not os.path.exists(input_file_path):
            logger.critical(
                to_red(f'input_file_path : "{input_file_path}" does not exist.')
            )
            logger.critical(to_red(f"FileNotFoundError"))
            exit(1)
        self.input_file_path: str = input_file_path
        self.outputs.clear()
        self.added_file.clear()
        self._get_code(self.input_file_path)
        output_code = "".join(self.outputs)
        if output_fie_path in ["clip"]:
            output_fie_path = "clipboard"
            pyperclip.copy(output_code)
        else:
            with open(output_fie_path, "w", encoding="utf-8") as f:
                f.write(output_code)
        logger.info(to_green("The process completed successfully."))
        logger.info(to_green(f'Output file: "{output_fie_path}".'))

    def _get_code(self, input_file_path: str) -> None:
        input_line_num = 0
        with open(input_file_path, "r", encoding="utf-8") as input_file:
            for line in input_file:
                input_line_num += 1
                if line.startswith(f'#include "titan_cpplib'):
                    _, s = line.split()
                    target_file = s.replace('"', "")
                    if target_file in self.added_file:
                        continue
                    self.added_file.add(target_file)
                    for lib_path in LIB_PATH:
                        new_path = f"{lib_path}{target_file}"
                        if os.path.exists(new_path):
                            self.outputs.append(f"// {line}")
                            logger.info(
                                f"[include] \"{target_file.replace(lib_path, '')}\""
                            )
                            self._get_code(new_path)
                            break
                    else:
                        logger.critical(
                            f'File "{input_file_path}", line {input_line_num}'
                        )
                        error_line = line.rstrip()
                        error_underline = "^" + "~" * (len(error_line) - 1)
                        logger.critical(to_red(f"\t{error_line}"))
                        logger.critical(to_red(f"\t{error_underline}"))
                        logger.critical(to_red(f"FileNotFoundError"))
                        exit(1)
                elif line.startswith("#pragma once"):
                    pass
                else:
                    self.outputs.append(line)


if __name__ == "__main__":
    basicConfig(
        format="%(asctime)s [%(levelname)s] : %(message)s",
        datefmt="%H:%M:%S",
        level=os.getenv("LOG_LEVEL", "INFO"),
    )
    CppExpander.init_clipboard()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input_file_path",
    )
    parser.add_argument(
        "-o",
        "--output_path",
        default="clip",
        action="store",
    )

    args = parser.parse_args()

    expander = CppExpander()
    expander.expand(args.input_file_path, args.output_path)
