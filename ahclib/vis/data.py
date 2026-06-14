import os
import sys
import re
import shutil
import importlib
from datetime import datetime

import pandas as pd

from . import config


def get_ahc_setting(key, default):
    """カレントの ahc_settings.py から AHCSettings の属性を読む"""
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        import ahc_settings

        importlib.reload(ahc_settings)
        return getattr(ahc_settings.AHCSettings, key, default)
    except Exception:
        return default


def format_timestamp(ts):
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y%m%d_%H%M"):
        try:
            return datetime.strptime(ts, fmt).strftime("%Y/%m/%d %H:%M")
        except ValueError:
            continue
    return ts


class ResultStore:
    """実行結果の読み込み・キャッシュ・集計を集約する"""

    def __init__(self, base_path=None, direction=None):
        self.base_path = base_path or config.BASE_PATH
        self.direction = direction or get_ahc_setting("direction", "minimize")
        self._csv_cache = {}
        self._frame_cache = None
        self._meta_cache = None
        self._meta_in_files = []
        self._meta_settings_mtime = 0

    def _scan(self):
        """フォルダ一覧と各 result.csv の mtime の組を返す"""
        if not os.path.exists(self.base_path):
            return []
        entries = []
        for folder in sorted(os.listdir(self.base_path)):
            csv_path = os.path.join(self.base_path, folder, config.FILE_NAME)
            if os.path.exists(csv_path):
                entries.append((folder, os.path.getmtime(csv_path)))
        return entries

    def long_frame(self):
        """全実行を結合した DataFrame を返す。署名が変わらなければ再結合しない"""
        empty_df = pd.DataFrame(
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
            k: v
            for k, v in self._csv_cache.items()
            if os.path.basename(k) in current_folders
        }

        data = []
        for folder, mtime in entries:
            folder_path = os.path.join(self.base_path, folder)
            csv_path = os.path.join(folder_path, config.FILE_NAME)
            try:
                if (
                    folder_path in self._csv_cache
                    and self._csv_cache[folder_path][0] == mtime
                ):
                    df = self._csv_cache[folder_path][1]
                else:
                    df = pd.read_csv(csv_path)
                    df["timestamp"] = folder
                    df["name"] = df["filename"].str.extract(r"(\d{4}\.txt)")
                    df["test_id"] = df["filename"].str.extract(r"(\d{4}\.txt)")
                    self._csv_cache[folder_path] = (mtime, df)
                data.append(df)
            except Exception:
                pass

        frame = pd.concat(data, ignore_index=True) if data else empty_df
        self._frame_cache = (signature, frame)
        return frame

    def refresh(self):
        """次回 long_frame() で再走査されるようキャッシュを無効化する"""
        self._frame_cache = None

    def compare(self, base_ts, target_ts):
        """Base と Target のケースごとスコアを突き合わせた DataFrame を返す"""
        cols = ["test_id", "name", "base", "target", "delta", "rel"]
        df = self.long_frame()
        if df.empty or base_ts is None or target_ts is None:
            return pd.DataFrame(columns=cols)

        base = df[df["timestamp"] == base_ts][["test_id", "name", "score"]].rename(
            columns={"score": "base"}
        )
        target = df[df["timestamp"] == target_ts][["test_id", "score"]].rename(
            columns={"score": "target"}
        )
        merged = pd.merge(base, target, on="test_id", how="inner")
        merged["base"] = pd.to_numeric(merged["base"], errors="coerce")
        merged["target"] = pd.to_numeric(merged["target"], errors="coerce")
        merged["delta"] = merged["target"] - merged["base"]
        merged["rel"] = merged["target"] / merged["base"].replace(0, pd.NA)
        return merged[cols]

    def paired_stats(self, base_ts, target_ts):
        """Base と Target の勝敗件数と Wilcoxon 検定の p 値を返す"""
        from scipy.stats import wilcoxon

        result = {"n": 0, "win": 0, "lose": 0, "tie": 0, "p": None}
        cmp = self.compare(base_ts, target_ts)
        cmp = cmp.dropna(subset=["base", "target"])
        if cmp.empty:
            return result

        delta = cmp["delta"]
        if self.direction == "minimize":
            win = int((delta < 0).sum())
            lose = int((delta > 0).sum())
        else:
            win = int((delta > 0).sum())
            lose = int((delta < 0).sum())
        tie = int((delta == 0).sum())

        result.update(n=len(cmp), win=win, lose=lose, tie=tie)

        if (delta != 0).any():
            try:
                _, p = wilcoxon(cmp["target"], cmp["base"])
                result["p"] = float(p)
            except Exception:
                result["p"] = None
        return result

    def out_err(self, timestamp, filename):
        err_path = os.path.join(self.base_path, timestamp, "err", filename)
        out_path = os.path.join(self.base_path, timestamp, "out", filename)

        err_text = "(errファイルなし)"
        out_text = "(outファイルなし)"

        if os.path.exists(err_path):
            with open(err_path, "r", encoding="utf-8", errors="ignore") as f:
                err_text = f.read()
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
                out_text = f.read()

        return err_text, out_text

    def source(self, timestamp):
        """保存された ahc_settings.py の filename か、無ければソースらしき1ファイルを読む"""
        dir_path = os.path.join(self.base_path, timestamp)
        settings_path = os.path.join(dir_path, "ahc_settings.py")
        src_filename = None

        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    m = re.search(r'filename\s*=\s*["\'](.*?)["\']', content)
                    if m:
                        src_filename = os.path.basename(m.group(1))
            except Exception:
                pass

        if not src_filename and os.path.exists(dir_path):
            for f in os.listdir(dir_path):
                if (
                    f.endswith(".cpp") or f.endswith(".py") or f.endswith(".rs")
                ) and f not in ["ahc_settings.py", "result.csv"]:
                    src_filename = f
                    break

        if not src_filename:
            src_filename = "main.cpp"

        src_path = os.path.join(dir_path, src_filename)
        if os.path.exists(src_path):
            with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(), src_filename

        fallback_path = os.path.join(dir_path, ".", src_filename)
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(), src_filename

        return "(ソースコードが保存されていません)", src_filename

    def in_file(self, filename):
        in_path = os.path.join(config.in_dir(), filename)
        if os.path.exists(in_path):
            try:
                with open(in_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
        return ""

    def get_memo(self, timestamp):
        memo_path = os.path.join(self.base_path, timestamp, "memo.txt")
        if os.path.exists(memo_path):
            try:
                with open(memo_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    def save_memo(self, timestamp, text):
        memo_path = os.path.join(self.base_path, timestamp, "memo.txt")
        try:
            with open(memo_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

    def delete(self, timestamp):
        dir_path = os.path.join(self.base_path, timestamp)
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)

    def meta(self):
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

        meta = []
        custom_parser = None
        try:
            if os.getcwd() not in sys.path:
                sys.path.append(os.getcwd())
            import ahc_settings

            importlib.reload(ahc_settings)
            if hasattr(ahc_settings.AHCSettings, "parse_input_params"):
                custom_parser = ahc_settings.AHCSettings.parse_input_params
        except Exception:
            pass

        for fname in current_files:
            path = os.path.join(in_path, fname)
            if custom_parser:
                try:
                    params = custom_parser(path)
                    params["test_id"] = fname
                    meta.append(params)
                    continue
                except Exception:
                    pass
            try:
                with open(path, "r", encoding="utf-8") as f:
                    line = f.readline().strip()
                    nums = [int(x) for x in line.split() if x.lstrip("-").isdigit()]
                    param = float(nums[0]) if nums else float(os.path.getsize(path))
                meta.append({"test_id": fname, "Param": param})
            except Exception:
                meta.append({"test_id": fname, "Param": 0.0})

        if meta:
            self._meta_cache = pd.DataFrame(meta)
        else:
            self._meta_cache = pd.DataFrame(columns=["test_id", "Param"])

        self._meta_in_files = current_files
        self._meta_settings_mtime = current_settings_mtime

        return self._meta_cache.copy()
