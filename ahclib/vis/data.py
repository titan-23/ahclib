import importlib
import os
import re
import shutil
import sys
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from . import config


def get_ahc_setting(key: str, default: Any) -> Any:
    """カレントの ahc_settings.py から AHCSettings の属性を読む"""
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        import ahc_settings

        importlib.reload(ahc_settings)
        return getattr(ahc_settings.AHCSettings, key, default)
    except Exception:
        return default


def format_timestamp(timestamp: str) -> str:
    for timestamp_format in ("%Y_%m_%d_%H_%M_%S", "%Y%m%d_%H%M"):
        try:
            return datetime.strptime(timestamp, timestamp_format).strftime(
                "%Y/%m/%d %H:%M"
            )
        except ValueError:
            continue
    return timestamp


class ResultStore:
    """実行結果の読み込み・キャッシュ・集計を集約する"""

    def __init__(
        self,
        base_path: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> None:
        self.base_path = base_path or config.BASE_PATH
        self.direction = direction or get_ahc_setting("direction", "minimize")
        self._csv_cache = {}
        self._frame_cache = None
        self._meta_cache = None
        self._meta_in_files = []
        self._meta_settings_mtime = 0

    def _scan(self) -> list[tuple[str, float]]:
        """結果ディレクトリ名と result.csv の更新日時を返す"""
        if not os.path.exists(self.base_path):
            return []
        entries = []
        for folder in sorted(os.listdir(self.base_path)):
            csv_path = os.path.join(self.base_path, folder, config.FILE_NAME)
            if os.path.exists(csv_path):
                entries.append((folder, os.path.getmtime(csv_path)))
        return entries

    def long_frame(self) -> pd.DataFrame:
        """全実行を結合した DataFrame を返し、変更がなければキャッシュを使う"""
        empty_frame = pd.DataFrame(
            columns=[
                "filename",
                "score",
                "state",
                "time",
                "timestamp",
                "name",
                "test_id",
            ]
        )
        entries = self._scan()
        signature = tuple(entries)
        if self._frame_cache is not None and self._frame_cache[0] == signature:
            return self._frame_cache[1]

        current_folders = [folder for folder, _ in entries]
        self._csv_cache = {
            folder_path: cached_data
            for folder_path, cached_data in self._csv_cache.items()
            if os.path.basename(folder_path) in current_folders
        }

        frames = []
        for folder, mtime in entries:
            folder_path = os.path.join(self.base_path, folder)
            csv_path = os.path.join(folder_path, config.FILE_NAME)
            try:
                if (
                    folder_path in self._csv_cache
                    and self._csv_cache[folder_path][0] == mtime
                ):
                    frame = self._csv_cache[folder_path][1]
                else:
                    frame = pd.read_csv(csv_path)
                    frame["timestamp"] = folder
                    frame["name"] = frame["filename"].str.extract(r"(\d{4}\.txt)")
                    frame["test_id"] = frame["filename"].str.extract(r"(\d{4}\.txt)")
                    self._csv_cache[folder_path] = (mtime, frame)
                frames.append(frame)
            except Exception:
                pass

        frame = pd.concat(frames, ignore_index=True) if frames else empty_frame
        self._frame_cache = (signature, frame)
        return frame

    def refresh(self) -> None:
        """次回の long_frame() で再走査するようキャッシュを無効化する"""
        self._frame_cache = None

    def compare(
        self,
        base_ts: Optional[str],
        target_ts: Optional[str],
    ) -> pd.DataFrame:
        """基準と比較対象のスコアをケースごとに対応付ける"""
        columns = ["test_id", "name", "base", "target", "delta", "rel"]
        frame = self.long_frame()
        if frame.empty or base_ts is None or target_ts is None:
            return pd.DataFrame(columns=columns)

        base = frame[frame["timestamp"] == base_ts][
            ["test_id", "name", "score"]
        ].rename(columns={"score": "base"})
        target = frame[frame["timestamp"] == target_ts][["test_id", "score"]].rename(
            columns={"score": "target"}
        )
        merged = pd.merge(base, target, on="test_id", how="inner")
        merged["base"] = pd.to_numeric(merged["base"], errors="coerce")
        merged["target"] = pd.to_numeric(merged["target"], errors="coerce")
        merged["delta"] = merged["target"] - merged["base"]
        merged["rel"] = merged["target"] / merged["base"].replace(0, pd.NA)
        return merged[columns]

    def paired_stats(
        self,
        base_ts: Optional[str],
        target_ts: Optional[str],
    ) -> dict[str, Any]:
        """基準と比較対象の勝敗件数と Wilcoxon 検定の p 値を返す"""
        from scipy.stats import wilcoxon

        result = {"n": 0, "win": 0, "lose": 0, "tie": 0, "p": None}
        comparison = self.compare(base_ts, target_ts)
        comparison = comparison.dropna(subset=["base", "target"])
        if comparison.empty:
            return result

        delta = comparison["delta"]
        if self.direction == "minimize":
            win = int((delta < 0).sum())
            lose = int((delta > 0).sum())
        else:
            win = int((delta > 0).sum())
            lose = int((delta < 0).sum())
        tie = int((delta == 0).sum())

        result.update(n=len(comparison), win=win, lose=lose, tie=tie)

        if (delta != 0).any():
            try:
                _, p_value = wilcoxon(comparison["target"], comparison["base"])
                result["p"] = float(p_value)
            except Exception:
                result["p"] = None
        return result

    def out_err(self, timestamp: str, filename: str) -> tuple[str, str]:
        err_path = os.path.join(self.base_path, timestamp, "err", filename)
        out_path = os.path.join(self.base_path, timestamp, "out", filename)

        err_text = "(errファイルなし)"
        out_text = "(outファイルなし)"

        if os.path.exists(err_path):
            with open(err_path, "r", encoding="utf-8", errors="ignore") as error_file:
                err_text = error_file.read()
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8", errors="ignore") as output_file:
                out_text = output_file.read()

        return err_text, out_text

    def source(self, timestamp: str) -> tuple[str, str]:
        """保存された ahc_settings.py の filename か、無ければソースらしき 1 ファイルを読む"""
        dir_path = os.path.join(self.base_path, timestamp)
        settings_path = os.path.join(dir_path, "ahc_settings.py")
        src_filename = None

        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as settings_file:
                    content = settings_file.read()
                    filename_match = re.search(
                        r'filename\s*=\s*["\'](.*?)["\']', content
                    )
                    if filename_match:
                        src_filename = os.path.basename(filename_match.group(1))
            except Exception:
                pass

        if not src_filename and os.path.exists(dir_path):
            for filename in os.listdir(dir_path):
                if (
                    filename.endswith(".cpp")
                    or filename.endswith(".py")
                    or filename.endswith(".rs")
                ) and filename not in ["ahc_settings.py", "result.csv"]:
                    src_filename = filename
                    break

        if not src_filename:
            src_filename = "main.cpp"

        src_path = os.path.join(dir_path, src_filename)
        if os.path.exists(src_path):
            with open(src_path, "r", encoding="utf-8", errors="ignore") as source_file:
                return source_file.read(), src_filename

        fallback_path = os.path.join(dir_path, ".", src_filename)
        if os.path.exists(fallback_path):
            with open(
                fallback_path, "r", encoding="utf-8", errors="ignore"
            ) as source_file:
                return source_file.read(), src_filename

        return "(ソースコードが保存されていません)", src_filename

    def in_file(self, filename: str) -> str:
        in_path = os.path.join(config.in_dir(), filename)
        if os.path.exists(in_path):
            try:
                with open(in_path, "r", encoding="utf-8") as input_file:
                    return input_file.read()
            except Exception:
                return ""
        return ""

    def get_memo(self, timestamp: str) -> str:
        memo_path = os.path.join(self.base_path, timestamp, "memo.txt")
        if os.path.exists(memo_path):
            try:
                with open(memo_path, "r", encoding="utf-8") as memo_file:
                    return memo_file.read().strip()
            except Exception:
                pass
        return ""

    def save_memo(self, timestamp: str, text: str) -> None:
        memo_path = os.path.join(self.base_path, timestamp, "memo.txt")
        try:
            with open(memo_path, "w", encoding="utf-8") as memo_file:
                memo_file.write(text)
        except Exception:
            pass

    def delete(self, timestamp: str) -> None:
        dir_path = os.path.join(self.base_path, timestamp)
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)

    def meta(self) -> pd.DataFrame:
        """./in/ 以下を parse_input_params で解析したパラメータ表を返す"""
        in_path = config.in_dir()
        if not os.path.exists(in_path):
            return pd.DataFrame(columns=["test_id", "Param"])

        current_files = sorted([f for f in os.listdir(in_path) if f.endswith(".txt")])
        settings_path = os.path.join(os.getcwd(), "ahc_settings.py")
        current_settings_mtime = (
            os.path.getmtime(settings_path) if os.path.exists(settings_path) else 0
        )

        if (
            self._meta_cache is not None
            and self._meta_in_files == current_files
            and self._meta_settings_mtime == current_settings_mtime
        ):
            return self._meta_cache.copy()

        metadata = []
        input_parser = None
        try:
            if os.getcwd() not in sys.path:
                sys.path.append(os.getcwd())
            import ahc_settings

            importlib.reload(ahc_settings)
            if hasattr(ahc_settings.AHCSettings, "parse_input_params"):
                input_parser = ahc_settings.AHCSettings.parse_input_params
        except Exception:
            pass

        for filename in current_files:
            path = os.path.join(in_path, filename)
            if input_parser:
                try:
                    parameters = input_parser(path)
                    parameters["test_id"] = filename
                    metadata.append(parameters)
                    continue
                except Exception:
                    pass
            try:
                with open(path, "r", encoding="utf-8") as input_file:
                    line = input_file.readline().strip()
                    numbers = [
                        int(value)
                        for value in line.split()
                        if value.lstrip("-").isdigit()
                    ]
                    parameter_value = (
                        float(numbers[0]) if numbers else float(os.path.getsize(path))
                    )
                metadata.append({"test_id": filename, "Param": parameter_value})
            except Exception:
                metadata.append({"test_id": filename, "Param": 0.0})

        if metadata:
            self._meta_cache = pd.DataFrame(metadata)
        else:
            self._meta_cache = pd.DataFrame(columns=["test_id", "Param"])

        self._meta_in_files = current_files
        self._meta_settings_mtime = current_settings_mtime

        return self._meta_cache.copy()
