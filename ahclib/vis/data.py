import importlib
import json
import logging
import math
import os
import posixpath
import re
import shutil
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Optional

import pandas as pd

from . import config

logger = logging.getLogger(__name__)

TEXT_CACHE_MAX_FILES = 32
TEXT_CACHE_MAX_CHARS = 8_000_000


@dataclass(frozen=True)
class ResultSnapshot:
    """同じ版の結果、集計、入力パラメータ、警告をまとめる"""

    version: int
    signature: tuple[Any, ...]
    results: pd.DataFrame
    run_summary: pd.DataFrame
    metadata: pd.DataFrame
    warnings: tuple[str, ...]
    run_indices: Mapping[str, tuple[int, ...]]
    case_indices: Mapping[tuple[str, str], int]

    def run(self, timestamp: Optional[str]) -> pd.DataFrame:
        if timestamp is None or self.results.empty:
            return self.results.iloc[0:0].copy()
        indices = self.run_indices.get(timestamp, ())
        return self.results.iloc[list(indices)].copy()

    def case(self, timestamp: str, case_id: str) -> Optional[dict[str, Any]]:
        index = self.case_indices.get((timestamp, case_id))
        if index is None:
            return None
        return self.results.iloc[index].to_dict()


def normalize_case_id(filename: object) -> str:
    """入力ファイル名を実行間で比較できる ID へ正規化する"""
    normalized = str(filename).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return posixpath.normpath(normalized)


def unique_case_ids(filenames: Iterable[object]) -> list[str]:
    """重複する入力へ出現順の接尾辞を付けた一意な ID を返す"""
    counts: dict[str, int] = {}
    result = []
    for filename in filenames:
        case_id = normalize_case_id(filename)
        duplicate_number = counts.get(case_id, 0)
        counts[case_id] = duplicate_number + 1
        result.append(
            case_id if duplicate_number == 0 else f"{case_id}#{duplicate_number}"
        )
    return result


def calculate_relative_scores(
    scores: pd.Series,
    baseline_scores: pd.Series,
) -> pd.Series:
    """比較不能な値を欠損にした相対スコアを返す"""
    numeric_scores = pd.to_numeric(scores, errors="coerce")
    numeric_baseline = pd.to_numeric(baseline_scores, errors="coerce")
    return numeric_scores.div(numeric_baseline.where(numeric_baseline != 0))


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
        read_only: bool = False,
    ) -> None:
        self.base_path = base_path or config.BASE_PATH
        self.direction = direction or get_ahc_setting("direction", "minimize")
        self.read_only = read_only
        self._csv_cache: dict[
            str,
            tuple[tuple[int, int], pd.DataFrame],
        ] = {}
        self._frame_cache: Optional[
            tuple[tuple[tuple[str, int, int], ...], pd.DataFrame]
        ] = None
        self._version = 0
        self._comparison_cache: dict[
            tuple[int, Optional[str], Optional[str]],
            pd.DataFrame,
        ] = {}
        self._meta_cache: Optional[pd.DataFrame] = None
        self._meta_signature: Optional[tuple[Any, ...]] = None
        self._metadata_settings_signature: Optional[tuple[str, int, int]] = None
        self._input_parser: Optional[Callable[[str], Mapping[str, Any]]] = None
        self._configured_input_files: Optional[list[str]] = None
        self._score_aggregator: Optional[Callable[[list[float]], float]] = None
        self._metadata_row_cache: dict[
            str,
            tuple[tuple[Any, ...], dict[str, Any], Optional[str]],
        ] = {}
        self._metadata_warnings: tuple[str, ...] = ()
        self._settings_warning: Optional[str] = None
        self._result_warnings: tuple[str, ...] = ()
        self._snapshot: Optional[ResultSnapshot] = None
        self._snapshot_version = 0
        self._lock = threading.RLock()
        self._text_cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self._text_cache_chars = 0
        self._run_annotation_cache: dict[
            str,
            tuple[tuple[Any, ...], dict[str, Any]],
        ] = {}

    @property
    def version(self) -> int:
        return self._version

    def _scan(self) -> list[tuple[str, int, int]]:
        """結果ディレクトリ名と result.csv の署名を返す"""
        if not os.path.exists(self.base_path):
            return []
        entries = []
        for folder in sorted(os.listdir(self.base_path)):
            csv_path = os.path.join(self.base_path, folder, config.FILE_NAME)
            if os.path.exists(csv_path):
                file_status = os.stat(csv_path)
                entries.append((folder, file_status.st_mtime_ns, file_status.st_size))
        return entries

    @staticmethod
    def _empty_result_frame() -> pd.DataFrame:
        return pd.DataFrame(
            columns=[
                "filename",
                "score",
                "state",
                "time",
                "timestamp",
                "name",
                "case_id",
                "test_id",
            ]
        )

    @staticmethod
    def _prepare_result_frame(frame: pd.DataFrame, timestamp: str) -> pd.DataFrame:
        required_columns = {"filename", "score", "time"}
        missing_columns = required_columns.difference(frame.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"result.csv に必要な列がありません: {missing}")

        prepared = frame.copy()
        if "state" not in prepared.columns:
            prepared["state"] = ""
        else:
            prepared["state"] = prepared["state"].fillna("").astype(str)
        prepared["timestamp"] = timestamp
        normalized_ids = prepared["filename"].map(normalize_case_id)
        prepared["case_id"] = unique_case_ids(list(prepared["filename"]))
        prepared["name"] = normalized_ids.map(posixpath.basename)
        prepared["test_id"] = prepared["case_id"]
        return prepared

    def long_frame(self) -> pd.DataFrame:
        """全実行を結合した DataFrame を返し、変更がなければキャッシュを使う"""
        with self._lock:
            return self._load_results()

    def _load_results(self) -> pd.DataFrame:
        empty_frame = self._empty_result_frame()
        entries = self._scan()
        signature = tuple(entries)
        if self._frame_cache is not None and self._frame_cache[0] == signature:
            return self._frame_cache[1]

        current_folders = [folder for folder, _, _ in entries]
        self._csv_cache = {
            folder_path: cached_data
            for folder_path, cached_data in self._csv_cache.items()
            if os.path.basename(folder_path) in current_folders
        }

        frames = []
        warnings = []
        for folder, mtime_ns, size in entries:
            folder_path = os.path.join(self.base_path, folder)
            csv_path = os.path.join(folder_path, config.FILE_NAME)
            file_signature = (mtime_ns, size)
            try:
                if (
                    folder_path in self._csv_cache
                    and self._csv_cache[folder_path][0] == file_signature
                ):
                    frame = self._csv_cache[folder_path][1]
                else:
                    frame = self._prepare_result_frame(pd.read_csv(csv_path), folder)
                    self._csv_cache[folder_path] = (file_signature, frame)
                frames.append(frame)
            except (OSError, ValueError, pd.errors.ParserError) as error:
                logger.warning("Failed to read %s: %s", csv_path, error)
                warnings.append(f"result.csv の読み込み失敗: {folder} ({error})")

        frame = pd.concat(frames, ignore_index=True) if frames else empty_frame
        self._frame_cache = (signature, frame)
        self._result_warnings = tuple(warnings)
        self._comparison_cache.clear()
        self._version += 1
        return frame

    def refresh(self) -> None:
        """次回の long_frame() で再走査するようキャッシュを無効化する"""
        with self._lock:
            self._frame_cache = None
            self._meta_cache = None
            self._snapshot = None
            self._comparison_cache.clear()

    def _build_run_summary(
        self,
        results: pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[str]]:
        columns = [
            "timestamp",
            "average_score",
            "median_score",
            "aggregate_score",
            "std_score",
            "iqr_score",
            "ci95_score",
            "case_count",
            "ng_cnt",
        ]
        if results.empty:
            return pd.DataFrame(columns=columns), []

        frame = results.copy()
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
        grouped = (
            frame.groupby("timestamp", sort=True)
            .agg(
                average_score=("score", "mean"),
                median_score=("score", "median"),
                std_score=("score", "std"),
                valid_score_count=("score", "count"),
                case_count=("case_id", "size"),
            )
            .reset_index()
        )
        quartiles = frame.groupby("timestamp")["score"].quantile([0.25, 0.75])
        grouped["iqr_score"] = grouped["timestamp"].map(
            lambda timestamp: (
                quartiles.get((timestamp, 0.75), float("nan"))
                - quartiles.get((timestamp, 0.25), float("nan"))
            )
        )
        grouped["ci95_score"] = grouped.apply(
            lambda row: (
                1.96 * row["std_score"] / math.sqrt(row["valid_score_count"])
                if row["valid_score_count"] > 1
                else float("nan")
            ),
            axis=1,
        )

        if "state" in frame.columns:
            failed_counts = (
                frame[~frame["state"].isin(["", "AC"])].groupby("timestamp").size()
            )
        else:
            failed_counts = pd.Series(dtype="int64")
        grouped["ng_cnt"] = (
            grouped["timestamp"].map(failed_counts).fillna(0).astype(int)
        )

        warnings = []
        aggregate_scores: dict[str, Optional[float]] = {}
        for timestamp, run in frame.groupby("timestamp", sort=False):
            scores = [float(score) for score in run["score"]]
            if self._score_aggregator is None:
                aggregate_scores[str(timestamp)] = None
                continue
            try:
                aggregate_scores[str(timestamp)] = float(self._score_aggregator(scores))
            except Exception as error:
                aggregate_scores[str(timestamp)] = None
                warnings.append(
                    f"AHCSettings.get_score の計算失敗: {timestamp} ({error})"
                )
        grouped["aggregate_score"] = grouped["timestamp"].map(aggregate_scores)
        return grouped[columns], warnings

    def _prepare_snapshot_results(self, results: pd.DataFrame) -> pd.DataFrame:
        prepared = results.copy()
        prepared["score"] = pd.to_numeric(prepared["score"], errors="coerce")
        prepared["time"] = pd.to_numeric(prepared["time"], errors="coerce")
        prepared["rank"] = prepared.groupby("timestamp")["score"].rank(
            method="min",
            ascending=self.direction == "minimize",
        )
        best_method = "min" if self.direction == "minimize" else "max"
        prepared["best"] = prepared.groupby("case_id")["score"].transform(best_method)
        return prepared

    def snapshot(self) -> ResultSnapshot:
        """現在の結果と関連情報を同じ版の snapshot として返す"""
        with self._lock:
            raw_results = self.long_frame()
            metadata = self.meta()
            result_signature = self._frame_cache[0] if self._frame_cache else ()
            signature = (result_signature, self._meta_signature)
            if self._snapshot is not None and self._snapshot.signature == signature:
                return self._snapshot

            results = self._prepare_snapshot_results(raw_results)
            run_summary, aggregate_warnings = self._build_run_summary(results)
            run_indices: dict[str, list[int]] = {}
            case_indices: dict[tuple[str, str], int] = {}
            for index, (timestamp, case_id) in enumerate(
                zip(results["timestamp"], results["case_id"])
            ):
                timestamp = str(timestamp)
                case_id = str(case_id)
                run_indices.setdefault(timestamp, []).append(index)
                case_indices.setdefault((timestamp, case_id), index)
            warnings = tuple(
                dict.fromkeys(
                    [
                        *self._result_warnings,
                        *self._metadata_warnings,
                        *aggregate_warnings,
                    ]
                )
            )
            self._comparison_cache.clear()
            self._snapshot_version += 1
            self._snapshot = ResultSnapshot(
                version=self._snapshot_version,
                signature=signature,
                results=results,
                run_summary=run_summary,
                metadata=metadata,
                warnings=warnings,
                run_indices=MappingProxyType(
                    {
                        timestamp: tuple(indices)
                        for timestamp, indices in run_indices.items()
                    }
                ),
                case_indices=MappingProxyType(case_indices),
            )
            return self._snapshot

    def compare(
        self,
        base_ts: Optional[str],
        target_ts: Optional[str],
        snapshot: Optional[ResultSnapshot] = None,
    ) -> pd.DataFrame:
        """基準と比較対象のスコアをケースごとに対応付ける"""
        columns = ["test_id", "name", "base", "target", "delta", "rel"]
        current = snapshot or self.snapshot()
        frame = current.results
        cache_key = (current.version, base_ts, target_ts)
        cached = self._comparison_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        if frame.empty or base_ts is None or target_ts is None:
            return pd.DataFrame(columns=columns)

        base = current.run(base_ts)[["test_id", "name", "score"]].rename(
            columns={"score": "base"}
        )
        target = current.run(target_ts)[["test_id", "score"]].rename(
            columns={"score": "target"}
        )
        merged = pd.merge(base, target, on="test_id", how="inner")
        merged["base"] = pd.to_numeric(merged["base"], errors="coerce")
        merged["target"] = pd.to_numeric(merged["target"], errors="coerce")
        merged["delta"] = merged["target"] - merged["base"]
        merged["rel"] = calculate_relative_scores(merged["target"], merged["base"])
        comparison = merged[columns]
        self._comparison_cache[cache_key] = comparison
        return comparison.copy()

    def paired_stats(
        self,
        base_ts: Optional[str],
        target_ts: Optional[str],
        comparison: Optional[pd.DataFrame] = None,
        snapshot: Optional[ResultSnapshot] = None,
    ) -> dict[str, Any]:
        """基準と比較対象の勝敗件数と Wilcoxon 検定の p 値を返す"""
        from scipy.stats import wilcoxon

        result = {"n": 0, "win": 0, "lose": 0, "tie": 0, "p": None}
        if comparison is None:
            comparison = self.compare(base_ts, target_ts, snapshot=snapshot)
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

    def _read_text(self, path: str, default: str = "") -> str:
        try:
            file_status = os.stat(path)
        except OSError:
            return default

        key = (
            os.path.realpath(path),
            file_status.st_mtime_ns,
            file_status.st_size,
        )
        with self._lock:
            cached = self._text_cache.get(key)
            if cached is not None:
                self._text_cache.move_to_end(key)
                return cached

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as text_file:
                text = text_file.read()
        except OSError:
            return default

        with self._lock:
            previous = self._text_cache.pop(key, None)
            if previous is not None:
                self._text_cache_chars -= len(previous)
            self._text_cache[key] = text
            self._text_cache_chars += len(text)
            while self._text_cache and (
                len(self._text_cache) > TEXT_CACHE_MAX_FILES
                or self._text_cache_chars > TEXT_CACHE_MAX_CHARS
            ):
                _old_key, old_text = self._text_cache.popitem(last=False)
                self._text_cache_chars -= len(old_text)
        return text

    def _invalidate_text_path(self, path: str) -> None:
        real_path = os.path.realpath(path)
        with self._lock:
            keys = [key for key in self._text_cache if key[0] == real_path]
            for key in keys:
                self._text_cache_chars -= len(self._text_cache.pop(key))

    @staticmethod
    def _file_signature(path: str) -> tuple[Optional[int], Optional[int]]:
        try:
            file_status = os.stat(path)
        except OSError:
            return None, None
        return file_status.st_mtime_ns, file_status.st_size

    def out_err(self, timestamp: str, filename: str) -> tuple[str, str]:
        run_path = self._run_dir(timestamp)
        safe_filename = os.path.basename(filename)
        err_path = os.path.join(run_path, "err", safe_filename)
        out_path = os.path.join(run_path, "out", safe_filename)

        err_text = "(err ファイルなし)"
        out_text = "(out ファイルなし)"

        err_text = self._read_text(err_path, err_text)
        out_text = self._read_text(out_path, out_text)

        return err_text, out_text

    def source(self, timestamp: str) -> tuple[str, str]:
        """保存された ahc_settings.py の filename か、無ければソースらしき 1 ファイルを読む"""
        dir_path = self._run_dir(timestamp)
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
            return self._read_text(src_path), src_filename

        fallback_path = os.path.join(dir_path, ".", src_filename)
        if os.path.exists(fallback_path):
            return self._read_text(fallback_path), src_filename

        return "(ソースコードが保存されていません)", src_filename

    def in_file(self, filename: str) -> str:
        in_path = (
            filename
            if os.path.exists(filename)
            else os.path.join(config.in_dir(), os.path.basename(filename))
        )
        return self._read_text(in_path)

    def visualizer_template(self) -> str:
        return self._read_text(config.vis_html_path())

    def _run_dir(self, timestamp: str) -> str:
        if not timestamp or os.path.basename(timestamp) != timestamp:
            raise ValueError("実行結果の名前が不正です")
        base_path = os.path.realpath(self.base_path)
        run_path = os.path.realpath(os.path.join(base_path, timestamp))
        if os.path.dirname(run_path) != base_path:
            raise ValueError("実行結果が結果ディレクトリの直下ではありません")
        return run_path

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise PermissionError("読み取り専用モードでは変更できません")

    def get_memo(self, timestamp: str) -> str:
        memo_path = os.path.join(self._run_dir(timestamp), "memo.txt")
        return self._read_text(memo_path).strip()

    def save_memo(self, timestamp: str, text: str) -> None:
        self._ensure_writable()
        memo_path = os.path.join(self._run_dir(timestamp), "memo.txt")
        with self._lock, open(memo_path, "w", encoding="utf-8") as memo_file:
            memo_file.write(text)
        self._invalidate_text_path(memo_path)
        with self._lock:
            self._run_annotation_cache.pop(timestamp, None)

    def _view_data(self, timestamp: str) -> dict[str, Any]:
        path = os.path.join(self._run_dir(timestamp), ".ahclib_vis.json")
        content = self._read_text(path)
        if not content:
            return {}
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_view_data(self, timestamp: str, data: Mapping[str, Any]) -> None:
        self._ensure_writable()
        path = os.path.join(self._run_dir(timestamp), ".ahclib_vis.json")
        temporary_path = f"{path}.{os.getpid()}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as output_file:
            json.dump(data, output_file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
        self._invalidate_text_path(path)
        self._run_annotation_cache.pop(timestamp, None)

    def get_tag(self, timestamp: str) -> str:
        return str(self._view_data(timestamp).get("tag") or "")

    def run_annotations(
        self,
        timestamps: Iterable[str],
    ) -> dict[str, dict[str, Any]]:
        with self._lock:
            timestamp_list = [str(timestamp) for timestamp in timestamps]
            current = set(timestamp_list)
            self._run_annotation_cache = {
                timestamp: cached
                for timestamp, cached in self._run_annotation_cache.items()
                if timestamp in current
            }

            annotations = {}
            for timestamp in timestamp_list:
                run_path = self._run_dir(timestamp)
                memo_path = os.path.join(run_path, "memo.txt")
                view_path = os.path.join(run_path, ".ahclib_vis.json")
                signature = (
                    *self._file_signature(memo_path),
                    *self._file_signature(view_path),
                )
                cached = self._run_annotation_cache.get(timestamp)
                if cached is not None and cached[0] == signature:
                    data = cached[1]
                else:
                    data = self._view_data(timestamp)
                    data["memo"] = self.get_memo(timestamp)
                    self._run_annotation_cache[timestamp] = (signature, data)
                annotations[timestamp] = data.copy()
            return annotations

    def save_tag(self, timestamp: str, tag: str) -> None:
        with self._lock:
            data = self._view_data(timestamp)
            data["tag"] = tag
            self._save_view_data(timestamp, data)

    def is_favorite(self, timestamp: str) -> bool:
        return bool(self._view_data(timestamp).get("favorite", False))

    def toggle_favorite(self, timestamp: str) -> bool:
        with self._lock:
            data = self._view_data(timestamp)
            favorite = not bool(data.get("favorite", False))
            data["favorite"] = favorite
            self._save_view_data(timestamp, data)
            return favorite

    def case_annotations(self, timestamp: Optional[str]) -> dict[str, dict[str, Any]]:
        if not timestamp:
            return {}
        notes = self.run_annotations([timestamp]).get(timestamp, {}).get("cases", {})
        if not isinstance(notes, dict):
            return {}
        return {
            str(case_id): value
            for case_id, value in notes.items()
            if isinstance(value, dict)
        }

    def save_case_memo(self, timestamp: str, case_id: str, memo: str) -> None:
        with self._lock:
            data = self._view_data(timestamp)
            notes = data.get("cases")
            if not isinstance(notes, dict):
                notes = {}
                data["cases"] = notes
            note = notes.get(case_id)
            if not isinstance(note, dict):
                note = {}
                notes[case_id] = note
            note["memo"] = memo
            self._save_view_data(timestamp, data)

    def toggle_case_bookmark(self, timestamp: str, case_id: str) -> bool:
        with self._lock:
            data = self._view_data(timestamp)
            notes = data.get("cases")
            if not isinstance(notes, dict):
                notes = {}
                data["cases"] = notes
            note = notes.get(case_id)
            if not isinstance(note, dict):
                note = {}
                notes[case_id] = note
            bookmark = not bool(note.get("bookmark", False))
            note["bookmark"] = bookmark
            self._save_view_data(timestamp, data)
            return bookmark

    def delete(self, timestamp: str) -> None:
        self._ensure_writable()
        dir_path = self._run_dir(timestamp)
        with self._lock:
            if os.path.isdir(dir_path):
                shutil.rmtree(dir_path)
            self._run_annotation_cache.pop(timestamp, None)

    def _load_metadata_settings(
        self,
        settings_path: str,
    ) -> tuple[
        Optional[Callable[[str], Mapping[str, Any]]],
        Optional[list[str]],
    ]:
        try:
            file_status = os.stat(settings_path)
            signature = (
                os.path.realpath(settings_path),
                file_status.st_mtime_ns,
                file_status.st_size,
            )
        except OSError:
            signature = (os.path.realpath(settings_path), 0, 0)

        if self._metadata_settings_signature == signature:
            return self._input_parser, self._configured_input_files

        input_parser = None
        configured_files = None
        score_aggregator = None
        settings_warning = None
        if os.path.exists(settings_path):
            try:
                if os.getcwd() not in sys.path:
                    sys.path.append(os.getcwd())
                import ahc_settings

                importlib.reload(ahc_settings)
                input_parser = getattr(
                    ahc_settings.AHCSettings,
                    "parse_input_params",
                    None,
                )
                input_files = getattr(
                    ahc_settings.AHCSettings,
                    "input_file_names",
                    None,
                )
                score_aggregator = getattr(
                    ahc_settings.AHCSettings,
                    "get_score",
                    None,
                )
                if input_files is not None:
                    configured_files = [str(path) for path in input_files]
            except Exception as error:
                settings_warning = f"ahc_settings.py の読み込み失敗 ({error})"
                logger.warning("Failed to load input metadata settings: %s", error)

        self._metadata_settings_signature = signature
        self._input_parser = input_parser
        self._configured_input_files = configured_files
        self._score_aggregator = score_aggregator
        self._settings_warning = settings_warning
        return input_parser, configured_files

    def meta(self) -> pd.DataFrame:
        """./in/ 以下を parse_input_params で解析したパラメータ表を返す"""
        with self._lock:
            return self._load_metadata()

    def _load_metadata(self) -> pd.DataFrame:
        in_path = config.in_dir()
        settings_path = os.path.join(os.getcwd(), "ahc_settings.py")
        input_parser, configured_files = self._load_metadata_settings(settings_path)

        if configured_files is not None:
            current_files = configured_files
        elif os.path.exists(in_path):
            current_files = [
                os.path.join(in_path, filename)
                for filename in sorted(os.listdir(in_path))
                if os.path.isfile(os.path.join(in_path, filename))
            ]
        else:
            current_files = []

        case_ids = unique_case_ids(current_files)
        file_signatures = []
        row_signatures = []
        for path, case_id in zip(current_files, case_ids):
            try:
                file_status = os.stat(path)
                file_signature = (
                    os.path.realpath(path),
                    file_status.st_mtime_ns,
                    file_status.st_size,
                    self._metadata_settings_signature,
                )
            except OSError:
                file_signature = (
                    os.path.realpath(path),
                    None,
                    None,
                    self._metadata_settings_signature,
                )
            row_signatures.append(file_signature)
            file_signatures.append((case_id, *file_signature))
        signature = (tuple(file_signatures), self._metadata_settings_signature)

        if self._meta_cache is not None and self._meta_signature == signature:
            return self._meta_cache.copy()

        metadata = []
        warnings = [self._settings_warning] if self._settings_warning else []
        current_ids = set(case_ids)
        self._metadata_row_cache = {
            case_id: cached
            for case_id, cached in self._metadata_row_cache.items()
            if case_id in current_ids
        }

        for path, case_id, row_signature in zip(
            current_files,
            case_ids,
            row_signatures,
        ):
            cached = self._metadata_row_cache.get(case_id)
            if cached is not None and cached[0] == row_signature:
                row = cached[1]
                warning = cached[2]
            else:
                row, warning = self._parse_metadata_row(
                    path,
                    case_id,
                    input_parser,
                )
                self._metadata_row_cache[case_id] = (
                    row_signature,
                    row,
                    warning,
                )
            metadata.append(row)
            if warning:
                warnings.append(warning)

        if metadata:
            self._meta_cache = pd.DataFrame(metadata)
        else:
            self._meta_cache = pd.DataFrame(columns=["test_id", "Param"])

        self._meta_signature = signature
        self._metadata_warnings = tuple(warnings)

        return self._meta_cache.copy()

    @staticmethod
    def _parse_metadata_row(
        path: str,
        case_id: str,
        input_parser: Optional[Callable[[str], Mapping[str, Any]]],
    ) -> tuple[dict[str, Any], Optional[str]]:
        parse_warning = None
        if input_parser:
            try:
                parameters = {
                    str(name): value for name, value in dict(input_parser(path)).items()
                }
                parameters["test_id"] = case_id
                return parameters, None
            except Exception as error:
                parse_warning = (
                    f"parse_input_params の失敗: {case_id} ({error})"
                    " 先頭の整数へ切り替え"
                )
                logger.warning(
                    "Failed to parse input parameters for %s: %s",
                    path,
                    error,
                )

        try:
            with open(path, "r", encoding="utf-8") as input_file:
                line = input_file.readline().strip()
                numbers = [
                    int(value) for value in line.split() if value.lstrip("-").isdigit()
                ]
                parameter_value = (
                    float(numbers[0]) if numbers else float(os.path.getsize(path))
                )
            return {"test_id": case_id, "Param": parameter_value}, parse_warning
        except (OSError, UnicodeError) as error:
            logger.warning("Failed to read input metadata for %s: %s", path, error)
            warning = f"入力パラメータの読み込み失敗: {case_id} ({error})"
            return {"test_id": case_id, "Param": None}, warning
