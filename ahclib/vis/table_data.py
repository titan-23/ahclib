from collections.abc import Callable, Mapping
import math
from typing import Any, Optional

import pandas as pd

from .data import calculate_relative_scores, format_timestamp

PARAMETER_FIELD_PREFIX = "__parameter_"


def parameter_column_specs(
    metadata: pd.DataFrame,
) -> list[tuple[object, str, bool]]:
    """入力パラメータの元の列名、表示用 field、数値列かを返す"""
    specs = []
    for column in metadata.columns:
        if column == "test_id":
            continue
        field = f"{PARAMETER_FIELD_PREFIX}{len(specs)}"
        is_numeric = bool(
            pd.api.types.is_numeric_dtype(metadata[column]) and not pd.api.types.is_bool_dtype(metadata[column])
        )
        specs.append((column, field, is_numeric))
    return specs


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    output = frame[columns].astype(object)
    output = output.where(pd.notna(output), None)
    return output.to_dict("records")


def selected_row_ids(selected_rows: Any) -> list[str]:
    """AG Grid の選択値から行 ID を取り出す"""
    if isinstance(selected_rows, dict):
        return [str(row_id) for row_id in selected_rows.get("ids", [])]
    if not isinstance(selected_rows, list):
        return []

    row_ids = []
    for row in selected_rows:
        if isinstance(row, dict):
            row_id = row.get("id")
            if row_id is not None:
                row_ids.append(str(row_id))
    return row_ids


def build_run_rows(
    all_results: pd.DataFrame,
    base_timestamp: Optional[str],
    memo_getter: Callable[[str], str],
    run_summary: Optional[pd.DataFrame] = None,
    tag_getter: Optional[Callable[[str], str]] = None,
    favorite_getter: Optional[Callable[[str], bool]] = None,
    run_annotations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """実行一覧用の行と実際に使った基準実行を返す"""
    if all_results.empty:
        return [], None

    frame = all_results.copy()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    timestamps = sorted(frame["timestamp"].dropna().astype(str).unique())
    if not timestamps:
        return [], None

    actual_base = base_timestamp if base_timestamp in timestamps else timestamps[0]
    baseline = frame[frame["timestamp"] == actual_base][["case_id", "score"]].rename(columns={"score": "base_score"})
    merged = pd.merge(frame, baseline, on="case_id", how="left")
    merged["rel_score"] = calculate_relative_scores(merged["score"], merged["base_score"])

    if run_summary is not None and not run_summary.empty:
        grouped = run_summary.copy()
    else:
        grouped = (
            merged.groupby("timestamp", sort=True)
            .agg(
                average_score=("score", "mean"),
                median_score=("score", "median"),
                std_score=("score", "std"),
                valid_score_count=("score", "count"),
                case_count=("case_id", "size"),
            )
            .reset_index()
        )
        grouped["aggregate_score"] = None
        grouped["iqr_score"] = None
        grouped["ci95_score"] = grouped.apply(
            lambda row: (
                1.96 * row["std_score"] / math.sqrt(row["valid_score_count"])
                if row["valid_score_count"] > 1
                else float("nan")
            ),
            axis=1,
        )
        if "state" in frame.columns:
            failed_counts = frame[~frame["state"].isin(["", "AC"])].groupby("timestamp").size()
            grouped["ng_cnt"] = grouped["timestamp"].map(failed_counts).fillna(0).astype(int)
        else:
            grouped["ng_cnt"] = 0

    valid_relative = merged[merged["rel_score"].notna() & (merged["rel_score"] > 0)]
    relative_summary = (
        valid_relative.groupby("timestamp")["rel_score"]
        .agg(
            rel_geo=lambda values: float(math.exp(values.map(math.log).mean())),
            rel_count="size",
        )
        .reset_index()
    )
    grouped = pd.merge(grouped, relative_summary, on="timestamp", how="left")
    grouped["rel_count"] = grouped["rel_count"].fillna(0).astype(int)
    grouped["rel_missing"] = grouped["case_count"] - grouped["rel_count"]

    grouped["formatted"] = grouped["timestamp"].map(format_timestamp)
    grouped["is_base_str"] = grouped["timestamp"].map(lambda timestamp: "★" if timestamp == actual_base else "・")
    grouped["delete_btn"] = "🗑️"
    if run_annotations is not None:
        grouped["memo"] = grouped["timestamp"].map(
            lambda timestamp: str(run_annotations.get(timestamp, {}).get("memo") or "")
        )
        grouped["tag"] = grouped["timestamp"].map(
            lambda timestamp: str(run_annotations.get(timestamp, {}).get("tag") or "")
        )
        grouped["favorite_str"] = grouped["timestamp"].map(
            lambda timestamp: ("★" if bool(run_annotations.get(timestamp, {}).get("favorite")) else "☆")
        )
    else:
        grouped["memo"] = grouped["timestamp"].map(memo_getter)
        grouped["tag"] = grouped["timestamp"].map(tag_getter if tag_getter is not None else lambda _timestamp: "")
        grouped["favorite_str"] = grouped["timestamp"].map(
            lambda timestamp: ("★" if favorite_getter is not None and favorite_getter(timestamp) else "☆")
        )
    grouped["id"] = grouped["timestamp"]

    columns = [
        "id",
        "timestamp",
        "favorite_str",
        "is_base_str",
        "formatted",
        "aggregate_score",
        "average_score",
        "median_score",
        "iqr_score",
        "ci95_score",
        "rel_geo",
        "rel_missing",
        "std_score",
        "case_count",
        "ng_cnt",
        "tag",
        "memo",
        "delete_btn",
    ]
    return _records(grouped, columns), actual_base


def _add_rank(
    frame: pd.DataFrame,
    score_column: str,
    rank_column: str,
    direction: str,
) -> None:
    frame[rank_column] = frame[score_column].rank(
        method="min",
        ascending=direction == "minimize",
    )


def build_case_rows(
    all_results: pd.DataFrame,
    target_timestamp: Optional[str],
    base_timestamp: Optional[str],
    direction: str,
    metadata: Optional[pd.DataFrame] = None,
    non_accepted_only: bool = False,
    comparison_filters: Optional[list[str]] = None,
    annotations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """詳細結果用のケース行を作る"""
    if all_results.empty or not target_timestamp:
        return []

    frame = all_results.copy()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    frame["time"] = pd.to_numeric(frame["time"], errors="coerce")
    if "state" not in frame.columns:
        frame["state"] = ""

    best_results = None
    if "best" not in frame.columns:
        best_method = "min" if direction == "minimize" else "max"
        best_results = (
            frame.groupby("case_id")["score"].agg(best_method).reset_index().rename(columns={"score": "best"})
        )

    target = frame[frame["timestamp"] == target_timestamp].copy()
    if target.empty:
        return []
    if "rank" not in target.columns:
        _add_rank(target, "score", "rank", direction)

    if base_timestamp:
        baseline = frame[frame["timestamp"] == base_timestamp].copy()
        if "rank" not in baseline.columns:
            _add_rank(baseline, "score", "rank", direction)
        baseline = baseline[["case_id", "score", "time", "state", "rank"]].rename(
            columns={
                "score": "base_score",
                "time": "base_time",
                "state": "base_state",
                "rank": "base_rank",
            }
        )
        target = pd.merge(target, baseline, on="case_id", how="left")
    else:
        target["base_score"] = pd.NA
        target["base_time"] = pd.NA
        target["base_state"] = None
        target["base_rank"] = pd.NA

    target["score_delta"] = target["score"] - target["base_score"]
    target["time_delta"] = target["time"] - target["base_time"]
    target["rank_delta"] = target["rank"] - target["base_rank"]
    target["rel"] = calculate_relative_scores(target["score"], target["base_score"])
    target["abs_score_delta"] = target["score_delta"].abs()
    target["relative_gap"] = (target["rel"] - 1.0).abs()

    target["comparison"] = "比較不能"
    comparable = target["score_delta"].notna()
    improved = target["score_delta"] < 0 if direction == "minimize" else target["score_delta"] > 0
    worsened = target["score_delta"] > 0 if direction == "minimize" else target["score_delta"] < 0
    target.loc[comparable & improved, "comparison"] = "改善"
    target.loc[comparable & worsened, "comparison"] = "悪化"
    target.loc[comparable & (target["score_delta"] == 0), "comparison"] = "同点"
    failed = ~target["state"].isin(["", "AC"])
    target.loc[failed, "comparison"] = target.loc[failed, "state"]
    base_failed = (~failed) & target["base_state"].notna() & ~target["base_state"].isin(["", "AC"])
    target.loc[base_failed, "comparison"] = "Base " + target.loc[base_failed, "base_state"].astype(str)
    if best_results is not None:
        target = pd.merge(target, best_results, on="case_id", how="left")

    parameter_fields = []
    if metadata is not None and not metadata.empty and "test_id" in metadata.columns:
        specs = parameter_column_specs(metadata)
        if specs:
            parameter_fields = [field for _column, field, _numeric in specs]
            renamed_columns = {column: field for column, field, _numeric in specs}
            parameter_data = metadata[["test_id", *renamed_columns]].rename(columns=renamed_columns)
            parameter_data = parameter_data.drop_duplicates(
                subset="test_id",
                keep="first",
            )
            target = pd.merge(target, parameter_data, on="test_id", how="left")

    if "state" not in target.columns:
        target["state"] = ""
    target["bookmark_str"] = target["case_id"].map(
        lambda case_id: ("★" if bool((annotations or {}).get(str(case_id), {}).get("bookmark")) else "☆")
    )
    target["case_memo"] = target["case_id"].map(
        lambda case_id: str((annotations or {}).get(str(case_id), {}).get("memo") or "")
    )
    if non_accepted_only:
        target = target[~target["state"].isin(["", "AC"])]
    if comparison_filters:
        masks = []
        filter_map = {
            "improved": target["comparison"] == "改善",
            "worsened": target["comparison"] == "悪化",
            "same": target["comparison"] == "同点",
            "unavailable": target["comparison"] == "比較不能",
            "failed": ~target["comparison"].isin(["改善", "悪化", "同点", "比較不能"]),
            "bookmarked": target["bookmark_str"] == "★",
        }
        for filter_name in comparison_filters:
            if filter_name in filter_map:
                masks.append(filter_map[filter_name])
        if masks:
            combined_mask = masks[0]
            for mask in masks[1:]:
                combined_mask |= mask
            target = target[combined_mask]

    target["id"] = target["case_id"]
    target = target.sort_values("case_id", kind="stable")
    columns = [
        "id",
        "bookmark_str",
        "case_memo",
        "case_id",
        "filename",
        "name",
        "state",
        "base_state",
        "comparison",
        "score",
        "base_score",
        "score_delta",
        "abs_score_delta",
        "rel",
        "relative_gap",
        "rank",
        "base_rank",
        "rank_delta",
        "time",
        "base_time",
        "time_delta",
        "best",
        *parameter_fields,
    ]
    return _records(target, columns)
