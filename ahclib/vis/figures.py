from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .data import ResultSnapshot, ResultStore, calculate_relative_scores


def add_ts_count_label(
    frame: pd.DataFrame,
    sorted_timestamps: list[str],
) -> list[str]:
    """凡例用の ``timestamp (n=件数)`` 列を追加して表示順を返す"""
    counts = frame.groupby("timestamp").size()
    frame["ts_label"] = frame["timestamp"].map(lambda timestamp: f"{timestamp} (n={counts.get(timestamp, 0)})")
    return [f"{timestamp} (n={counts.get(timestamp, 0)})" for timestamp in sorted_timestamps]


def build_graph(
    store: ResultStore,
    snapshot: ResultSnapshot,
    selected_timestamps: Optional[list[str]],
    graph_type: str,
    param_x: Optional[str],
    param_y: Optional[str],
    log_scale: Optional[list[str]],
    target_ts: Optional[str],
    base_ts: Optional[str],
) -> tuple[go.Figure, str]:
    """グラフ種別に応じた Figure と要約文を返す"""
    direction = store.direction

    if not selected_timestamps or not target_ts:
        figure = px.line(title="（実行結果が選択されていません）")
        figure.update_layout(
            template="plotly_dark",
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#1e1e1e",
            plot_bgcolor="#1e1e1e",
        )
        return figure, ""

    all_results = snapshot.results

    all_timestamps = sorted(all_results["timestamp"].unique())
    if base_ts not in all_timestamps:
        base_ts = all_timestamps[0] if all_timestamps else None

    selected_timestamps = list(dict.fromkeys(selected_timestamps))
    selected_frames = [snapshot.run(timestamp) for timestamp in selected_timestamps]
    selected_results = pd.concat(selected_frames, ignore_index=True)
    selected_results = selected_results[pd.to_numeric(selected_results["score"], errors="coerce").notna()]
    if not selected_results.empty:
        selected_results["score"] = selected_results["score"].astype(float)

    if selected_results.empty:
        figure = px.line(title="（表示するデータがありません）")
        return figure, ""

    sorted_timestamps = sorted(selected_timestamps)

    if graph_type == "abs":
        label_order = add_ts_count_label(selected_results, sorted_timestamps)
        figure = px.line(
            selected_results,
            x="test_id",
            y="score",
            color="ts_label",
            markers=True,
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        figure.update_layout(yaxis_title="Score")

    elif graph_type == "rel":
        baseline_results = snapshot.run(base_ts)[["test_id", "score"]].rename(columns={"score": "base_score"})
        merged_results = pd.merge(selected_results, baseline_results, on="test_id", how="left")
        merged_results["relative_score"] = calculate_relative_scores(
            merged_results["score"], merged_results["base_score"]
        )
        label_order = add_ts_count_label(merged_results, sorted_timestamps)
        figure = px.line(
            merged_results,
            x="test_id",
            y="relative_score",
            color="ts_label",
            markers=True,
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        figure.add_hline(
            y=1.0,
            line_dash="dash",
            line_color="#888",
            annotation_text=f"Base: {base_ts}",
        )
        figure.update_layout(yaxis_title="Relative Score")

    elif graph_type == "box":
        counts = selected_results.groupby("timestamp").size()
        selected_results["ts_with_count"] = selected_results["timestamp"].apply(
            lambda timestamp: f"{timestamp}<br>(n={counts.get(timestamp,0)})"
        )
        sorted_timestamp_labels = [f"{timestamp}<br>(n={counts.get(timestamp,0)})" for timestamp in sorted_timestamps]
        figure = px.box(
            selected_results,
            x="ts_with_count",
            y="score",
            color="timestamp",
        )
        figure.update_xaxes(categoryorder="array", categoryarray=sorted_timestamp_labels)
        figure.update_layout(xaxis_title="Execution", yaxis_title="Score")

    elif graph_type.startswith("param_"):
        parameter_column = param_x
        metadata = snapshot.metadata
        if not metadata.empty and parameter_column in metadata.columns:
            merged_results = pd.merge(selected_results, metadata, on="test_id", how="left")
            if graph_type == "param_scatter":
                label_order = add_ts_count_label(merged_results, sorted_timestamps)
                figure = px.scatter(
                    merged_results,
                    x=parameter_column,
                    y="score",
                    color="ts_label",
                    hover_data=["test_id"],
                    category_orders={"ts_label": label_order},
                    labels={"ts_label": "timestamp"},
                    render_mode="webgl",
                )
            elif graph_type == "param_box":
                counts = merged_results.groupby(parameter_column)["test_id"].nunique()
                merged_results["param_label"] = merged_results[parameter_column].apply(
                    lambda value: f"{value} (n={counts.get(value, 0)})"
                )
                label_order = [
                    f"{value} (n={counts.get(value, 0)})"
                    for value in sorted(merged_results[parameter_column].dropna().unique())
                ]
                figure = px.box(
                    merged_results,
                    x="param_label",
                    y="score",
                    color="timestamp",
                    category_orders={
                        "timestamp": sorted_timestamps,
                        "param_label": label_order,
                    },
                )
            elif graph_type == "param_line":
                counts = merged_results.groupby(parameter_column)["test_id"].nunique()
                averaged_results = merged_results.groupby([parameter_column, "timestamp"])["score"].mean().reset_index()
                averaged_results["param_label"] = averaged_results[parameter_column].apply(
                    lambda value: f"{value} (n={counts.get(value, 0)})"
                )
                label_order = [
                    f"{value} (n={counts.get(value, 0)})"
                    for value in sorted(averaged_results[parameter_column].dropna().unique())
                ]
                figure = px.line(
                    averaged_results,
                    x="param_label",
                    y="score",
                    color="timestamp",
                    markers=True,
                    category_orders={
                        "timestamp": sorted_timestamps,
                        "param_label": label_order,
                    },
                )
            figure.update_layout(
                xaxis_title=f"Parameter: {parameter_column}",
                yaxis_title="Score",
            )
        else:
            figure = px.scatter(title="（パラメータ情報を取得できませんでした）")
            figure.update_layout(
                paper_bgcolor="#1e1e1e",
                plot_bgcolor="#1e1e1e",
            )

    elif graph_type in ["difficulty_box", "difficulty_heatmap"]:
        selection_count = len(selected_timestamps)
        summary_text = f"CV 分析: {selection_count} 件の実行結果"
        if selection_count < 2:
            summary_text += " ⚠️ 2件以上選択してください"
        variation_results = selected_results.copy()
        variation_results["score"] = pd.to_numeric(variation_results["score"], errors="coerce")
        variation_results = variation_results.dropna(subset=["score"])

        coefficient_variation = (
            variation_results.groupby("test_id")["score"]
            .agg(
                cv=lambda scores: (
                    scores.std() / abs(scores.mean())
                    if abs(scores.mean()) > 1e-12 and len(scores) > 1
                    else float("nan")
                )
            )
            .reset_index()
        )
        unavailable_count = int(coefficient_variation["cv"].isna().sum())
        if unavailable_count:
            summary_text += f" | CV 算出不能 {unavailable_count} 件"

        metadata = snapshot.metadata
        parameter_column = param_x

        if metadata.empty or parameter_column not in metadata.columns:
            figure = px.scatter(title="（パラメータ情報を取得できませんでした）")
            figure.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        else:
            merged_results = pd.merge(coefficient_variation, metadata, on="test_id", how="left")
            merged_results[parameter_column] = pd.to_numeric(merged_results[parameter_column], errors="coerce")
            merged_results = merged_results.dropna(subset=[parameter_column])

            if graph_type == "difficulty_box":
                counts = merged_results.groupby(parameter_column)["test_id"].nunique()
                merged_results["param_label"] = merged_results[parameter_column].apply(
                    lambda value: f"{value} (n={counts.get(value, 0)})"
                )
                label_order = [
                    f"{value} (n={counts.get(value, 0)})"
                    for value in sorted(merged_results[parameter_column].dropna().unique())
                ]
                figure = px.box(
                    merged_results,
                    x="param_label",
                    y="cv",
                    labels={
                        "param_label": f"Parameter: {parameter_column}",
                        "cv": "CV (std/abs(mean))",
                    },
                    category_orders={"param_label": label_order},
                )
                figure.update_traces(marker_color="#29b6f6")

            else:
                y_parameter_column = param_y
                if y_parameter_column not in metadata.columns:
                    figure = px.scatter(title="（Y 軸パラメータ情報を取得できませんでした）")
                    figure.update_layout(
                        paper_bgcolor="#1e1e1e",
                        plot_bgcolor="#1e1e1e",
                    )
                else:
                    merged_results[y_parameter_column] = pd.to_numeric(
                        merged_results[y_parameter_column], errors="coerce"
                    )
                    merged_results = merged_results.dropna(subset=[y_parameter_column])
                    x_counts = merged_results.groupby(parameter_column)["test_id"].nunique()
                    y_counts = merged_results.groupby(y_parameter_column)["test_id"].nunique()
                    average_variation = (
                        merged_results.groupby([y_parameter_column, parameter_column])["cv"].mean().reset_index()
                    )
                    pivot_table = average_variation.pivot(
                        index=y_parameter_column,
                        columns=parameter_column,
                        values="cv",
                    )
                    pivot_table = pivot_table.sort_index().sort_index(axis=1).astype(float)

                    figure = px.imshow(
                        pivot_table.values,
                        labels=dict(
                            x=f"{parameter_column}",
                            y=f"{y_parameter_column}",
                            color="CV Mean",
                        ),
                        x=[f"{value} (n={x_counts.get(value, 0)})" for value in pivot_table.columns],
                        y=[f"{value} (n={y_counts.get(value, 0)})" for value in pivot_table.index],
                        aspect="auto",
                        color_continuous_scale=[[0.0, "#1e1e1e"], [1.0, "#f44336"]],
                        origin="lower",
                        text_auto=".3f",
                    )
                    figure.update_layout(
                        xaxis_title=f"Parameter: {parameter_column}",
                        yaxis_title=f"Parameter: {y_parameter_column}",
                    )

    elif graph_type in ["heatmap_abs", "heatmap_rel"]:
        metadata = snapshot.metadata
        if not metadata.empty and param_x in metadata.columns and param_y in metadata.columns:
            heatmap_results = snapshot.run(target_ts)
            heatmap_results = heatmap_results[pd.to_numeric(heatmap_results["score"], errors="coerce").notna()]
            heatmap_results["score"] = heatmap_results["score"].astype(float)

            merged_results = pd.merge(heatmap_results, metadata, on="test_id", how="left")

            if graph_type == "heatmap_rel":
                baseline_results = snapshot.run(base_ts)[["test_id", "score"]].rename(columns={"score": "base_score"})
                merged_results = pd.merge(
                    merged_results,
                    baseline_results,
                    on="test_id",
                    how="left",
                )
                merged_results["val"] = calculate_relative_scores(merged_results["score"], merged_results["base_score"])
            else:
                merged_results["val"] = merged_results["score"]

            x_counts = merged_results.groupby(param_x)["test_id"].nunique()
            y_counts = merged_results.groupby(param_y)["test_id"].nunique()
            averaged_results = merged_results.groupby([param_y, param_x])["val"].mean().reset_index()
            pivot_table = averaged_results.pivot(index=param_y, columns=param_x, values="val")
            pivot_table = pivot_table.sort_index().sort_index(axis=1).astype(float)

            if direction == "minimize":
                if graph_type == "heatmap_rel":
                    color_scale = [[0.0, "#4caf50"], [0.5, "#1e1e1e"], [1.0, "#f44336"]]
                    color_midpoint = 1.0
                else:
                    color_scale = [[0.0, "#4caf50"], [1.0, "#f44336"]]
                    color_midpoint = None
            else:
                if graph_type == "heatmap_rel":
                    color_scale = [[0.0, "#f44336"], [0.5, "#1e1e1e"], [1.0, "#4caf50"]]
                    color_midpoint = 1.0
                else:
                    color_scale = [[0.0, "#f44336"], [1.0, "#4caf50"]]
                    color_midpoint = None

            text_format = ".3f" if graph_type == "heatmap_rel" else ".3s"

            minimum_value = pivot_table.min().min()
            maximum_value = pivot_table.max().max()
            safe_range = None
            if pd.notna(minimum_value) and minimum_value == maximum_value:
                safe_range = [minimum_value - 0.1, maximum_value + 0.1]
                color_midpoint = None

            figure = px.imshow(
                pivot_table.values,
                labels=dict(
                    x=f"{param_x}",
                    y=f"{param_y}",
                    color="Rel Ave" if graph_type == "heatmap_rel" else "Abs Ave",
                ),
                x=[f"{value} (n={x_counts.get(value, 0)})" for value in pivot_table.columns],
                y=[f"{value} (n={y_counts.get(value, 0)})" for value in pivot_table.index],
                aspect="auto",
                color_continuous_scale=color_scale,
                color_continuous_midpoint=color_midpoint,
                range_color=safe_range,
                origin="lower",
                text_auto=text_format,
            )
            figure.update_layout(
                xaxis_title=f"Parameter: {param_x}",
                yaxis_title=f"Parameter: {param_y}",
            )
        else:
            figure = px.scatter(title="（パラメータ情報を取得できませんでした）")
            figure.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")

    elif graph_type == "score_time":
        score_time_results = selected_results.copy()
        score_time_results["time"] = pd.to_numeric(score_time_results["time"], errors="coerce")
        score_time_results = score_time_results.dropna(subset=["time"])
        label_order = add_ts_count_label(score_time_results, sorted_timestamps)
        figure = px.scatter(
            score_time_results,
            x="time",
            y="score",
            color="ts_label",
            hover_data=["test_id"],
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        figure.update_layout(xaxis_title="Time (s)", yaxis_title="Score")

    elif graph_type == "regression":
        comparison = store.compare(base_ts, target_ts, snapshot=snapshot)
        comparison = comparison.dropna(subset=["base", "target"])
        if comparison.empty:
            figure = px.scatter(title="（比較できるデータがありません）")
            figure.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        else:
            ascending = direction == "maximize"
            comparison = comparison.sort_values("delta", ascending=ascending)
            if direction == "minimize":
                comparison["判定"] = comparison["delta"].apply(
                    lambda difference: ("改善" if difference < 0 else ("悪化" if difference > 0 else "同じ"))
                )
            else:
                comparison["判定"] = comparison["delta"].apply(
                    lambda difference: ("改善" if difference > 0 else ("悪化" if difference < 0 else "同じ"))
                )
            figure = px.bar(
                comparison,
                x="name",
                y="delta",
                color="判定",
                color_discrete_map={
                    "改善": "#4caf50",
                    "悪化": "#f44336",
                    "同じ": "#888",
                },
                hover_data=["base", "target", "rel"],
            )
            figure.update_xaxes(categoryorder="array", categoryarray=list(comparison["name"]))
            figure.update_layout(xaxis_title="Case", yaxis_title="Δ (Target - Base)")

    is_log = bool(log_scale and "log" in log_scale)

    if graph_type in ["heatmap_abs", "heatmap_rel", "difficulty_heatmap"]:
        yaxis_type = "category"
        xaxis_type = "category"
    else:
        yaxis_type = "log" if is_log else "linear"
        xaxis_type = None

    figure.update_layout(
        template="plotly_dark",
        hovermode="x unified" if graph_type in ["abs", "rel"] else "closest",
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="#1e1e1e",
        plot_bgcolor="#1e1e1e",
        uirevision="keep",
        yaxis_type=yaxis_type,
    )

    if xaxis_type:
        figure.update_layout(xaxis_type=xaxis_type)

    if graph_type == "heatmap_abs":
        summary_text = f"ヒートマップ対象: {target_ts}"
    elif graph_type == "heatmap_rel":
        summary_text = f"ヒートマップ対象: {target_ts} (Base: {base_ts})"
    elif graph_type in ["difficulty_box", "difficulty_heatmap"]:
        pass
    elif graph_type == "regression":
        statistics = store.paired_stats(
            base_ts,
            target_ts,
            comparison=comparison,
            snapshot=snapshot,
        )
        p_value_text = f"{statistics['p']:.3g}" if statistics["p"] is not None else "-"
        summary_text = (
            f"回帰: Target {target_ts} vs Base {base_ts} | "
            f"改善 {statistics['win']} / 悪化 {statistics['lose']} / "
            f"同 {statistics['tie']} (n={statistics['n']}) | "
            f"Wilcoxon p={p_value_text}"
        )
    else:
        summary_text = f"直近に選択したケース: {target_ts}"

    return figure, summary_text
