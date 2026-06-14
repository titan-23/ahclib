import pandas as pd
import plotly.express as px


def add_ts_count_label(frame, sorted_ts):
    """凡例用の `timestamp (n=件数)` ラベル列を追加し 表示順のリストを返す"""
    counts = frame.groupby("timestamp").size()
    frame["ts_label"] = frame["timestamp"].map(lambda t: f"{t} (n={counts.get(t, 0)})")
    return [f"{t} (n={counts.get(t, 0)})" for t in sorted_ts]


def build_graph(
    store, rows, graph_type, param_x, param_y, log_scale, target_ts, table_data, base_ts
):
    """グラフ種別に応じた figure と要約テキストを返す"""
    direction = store.direction

    valid_rows = [r for r in rows if r < len(table_data)] if rows else []
    if not valid_rows or not target_ts:
        fig = px.line(title="（実行結果が選択されていません）")
        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="#1e1e1e",
            plot_bgcolor="#1e1e1e",
        )
        return fig, ""

    selected_timestamps = [table_data[i]["timestamp"] for i in valid_rows]

    df_all = store.long_frame()

    all_timestamps = sorted(df_all["timestamp"].unique())
    if base_ts not in all_timestamps:
        base_ts = all_timestamps[0] if all_timestamps else None

    df = df_all[df_all["timestamp"].isin(selected_timestamps)]
    df = df[pd.to_numeric(df["score"], errors="coerce").notna()]
    if not df.empty:
        df["score"] = df["score"].astype(float)

    if df.empty:
        fig = px.line(title="（表示するデータがありません）")
        return fig, ""

    sorted_ts = sorted(selected_timestamps)

    if graph_type == "abs":
        label_order = add_ts_count_label(df, sorted_ts)
        fig = px.line(
            df,
            x="test_id",
            y="score",
            color="ts_label",
            markers=True,
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        fig.update_layout(yaxis_title="Score")

    elif graph_type == "rel":
        base_df = df_all[df_all["timestamp"] == base_ts][["test_id", "score"]].rename(
            columns={"score": "base_score"}
        )
        merged = pd.merge(df, base_df, on="test_id", how="left")
        merged["relative_score"] = merged.apply(
            lambda r: (
                r["score"] / r["base_score"]
                if pd.notna(r["base_score"]) and r["base_score"] != 0
                else 1.0
            ),
            axis=1,
        )
        label_order = add_ts_count_label(merged, sorted_ts)
        fig = px.line(
            merged,
            x="test_id",
            y="relative_score",
            color="ts_label",
            markers=True,
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        fig.add_hline(
            y=1.0,
            line_dash="dash",
            line_color="#888",
            annotation_text=f"Base: {base_ts}",
        )
        fig.update_layout(yaxis_title="Relative Score")

    elif graph_type == "box":
        counts = df.groupby("timestamp").size()
        df["ts_with_count"] = df["timestamp"].apply(
            lambda t: f"{t}<br>(n={counts.get(t,0)})"
        )
        sorted_ts_labels = [f"{t}<br>(n={counts.get(t,0)})" for t in sorted_ts]
        fig = px.box(df, x="ts_with_count", y="score", color="timestamp")
        fig.update_xaxes(categoryorder="array", categoryarray=sorted_ts_labels)
        fig.update_layout(xaxis_title="Execution", yaxis_title="Score")

    elif graph_type.startswith("param_"):
        param_col = param_x
        meta_df = store.meta()
        if not meta_df.empty and param_col in meta_df.columns:
            merged = pd.merge(df, meta_df, on="test_id", how="left")
            if graph_type == "param_scatter":
                label_order = add_ts_count_label(merged, sorted_ts)
                fig = px.scatter(
                    merged,
                    x=param_col,
                    y="score",
                    color="ts_label",
                    hover_data=["test_id"],
                    category_orders={"ts_label": label_order},
                    labels={"ts_label": "timestamp"},
                    render_mode="webgl",
                )
            elif graph_type == "param_box":
                counts = merged.groupby(param_col)["test_id"].nunique()
                merged["param_label"] = merged[param_col].apply(
                    lambda v: f"{v} (n={counts.get(v, 0)})"
                )
                label_order = [
                    f"{v} (n={counts.get(v, 0)})"
                    for v in sorted(merged[param_col].dropna().unique())
                ]
                fig = px.box(
                    merged,
                    x="param_label",
                    y="score",
                    color="timestamp",
                    category_orders={
                        "timestamp": sorted_ts,
                        "param_label": label_order,
                    },
                )
            elif graph_type == "param_line":
                counts = merged.groupby(param_col)["test_id"].nunique()
                avg_df = (
                    merged.groupby([param_col, "timestamp"])["score"]
                    .mean()
                    .reset_index()
                )
                avg_df["param_label"] = avg_df[param_col].apply(
                    lambda v: f"{v} (n={counts.get(v, 0)})"
                )
                label_order = [
                    f"{v} (n={counts.get(v, 0)})"
                    for v in sorted(avg_df[param_col].dropna().unique())
                ]
                fig = px.line(
                    avg_df,
                    x="param_label",
                    y="score",
                    color="timestamp",
                    markers=True,
                    category_orders={
                        "timestamp": sorted_ts,
                        "param_label": label_order,
                    },
                )
            fig.update_layout(
                xaxis_title=f"Parameter: {param_col}", yaxis_title="Score"
            )

    elif graph_type in ["difficulty_box", "difficulty_heatmap"]:
        n = len(selected_timestamps)
        summary_msg = f"CV分析: {n}件の実行結果"
        if n < 2:
            summary_msg += " ⚠️ 2件以上選択してください"
        df_cv = df_all[df_all["timestamp"].isin(selected_timestamps)].copy()
        df_cv["score"] = pd.to_numeric(df_cv["score"], errors="coerce")
        df_cv = df_cv.dropna(subset=["score"])

        cv_df = (
            df_cv.groupby("test_id")["score"]
            .agg(
                cv=lambda x: x.std() / x.mean() if x.mean() != 0 and len(x) > 1 else 0.0
            )
            .reset_index()
        )

        meta_df = store.meta()
        param_col = param_x

        if meta_df.empty or param_col not in meta_df.columns:
            fig = px.scatter(title="（パラメータ情報を取得できませんでした）")
            fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        else:
            merged = pd.merge(cv_df, meta_df, on="test_id", how="left")
            merged[param_col] = pd.to_numeric(merged[param_col], errors="coerce")
            merged = merged.dropna(subset=[param_col])

            if graph_type == "difficulty_box":
                counts = merged.groupby(param_col)["test_id"].nunique()
                merged["param_label"] = merged[param_col].apply(
                    lambda v: f"{v} (n={counts.get(v, 0)})"
                )
                label_order = [
                    f"{v} (n={counts.get(v, 0)})"
                    for v in sorted(merged[param_col].dropna().unique())
                ]
                fig = px.box(
                    merged,
                    x="param_label",
                    y="cv",
                    labels={
                        "param_label": f"Parameter: {param_col}",
                        "cv": "CV (std/mean)",
                    },
                    category_orders={"param_label": label_order},
                )
                fig.update_traces(marker_color="#29b6f6")

            else:
                param_col_y = param_y
                if param_col_y not in meta_df.columns:
                    fig = px.scatter(
                        title="（Y軸パラメータ情報を取得できませんでした）"
                    )
                    fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
                else:
                    merged[param_col_y] = pd.to_numeric(
                        merged[param_col_y], errors="coerce"
                    )
                    merged = merged.dropna(subset=[param_col_y])
                    cnt_x = merged.groupby(param_col)["test_id"].nunique()
                    cnt_y = merged.groupby(param_col_y)["test_id"].nunique()
                    avg_cv = (
                        merged.groupby([param_col_y, param_col])["cv"]
                        .mean()
                        .reset_index()
                    )
                    pivot_df = avg_cv.pivot(
                        index=param_col_y, columns=param_col, values="cv"
                    )
                    pivot_df = pivot_df.sort_index().sort_index(axis=1).astype(float)

                    fig = px.imshow(
                        pivot_df.values,
                        labels=dict(
                            x=f"{param_col}", y=f"{param_col_y}", color="CV Mean"
                        ),
                        x=[f"{x} (n={cnt_x.get(x, 0)})" for x in pivot_df.columns],
                        y=[f"{y} (n={cnt_y.get(y, 0)})" for y in pivot_df.index],
                        aspect="auto",
                        color_continuous_scale=[[0.0, "#1e1e1e"], [1.0, "#f44336"]],
                        origin="lower",
                        text_auto=".3f",
                    )
                    fig.update_layout(
                        xaxis_title=f"Parameter: {param_col}",
                        yaxis_title=f"Parameter: {param_col_y}",
                    )

    elif graph_type in ["heatmap_abs", "heatmap_rel"]:
        meta_df = store.meta()
        if (
            not meta_df.empty
            and param_x in meta_df.columns
            and param_y in meta_df.columns
        ):
            df_hm = df_all[df_all["timestamp"] == target_ts]
            df_hm = df_hm[pd.to_numeric(df_hm["score"], errors="coerce").notna()]
            df_hm["score"] = df_hm["score"].astype(float)

            merged = pd.merge(df_hm, meta_df, on="test_id", how="left")

            if graph_type == "heatmap_rel":
                base_df = df_all[df_all["timestamp"] == base_ts][
                    ["test_id", "score"]
                ].rename(columns={"score": "base_score"})
                merged = pd.merge(merged, base_df, on="test_id", how="left")
                merged["val"] = merged.apply(
                    lambda r: (
                        r["score"] / r["base_score"]
                        if pd.notna(r["base_score"]) and r["base_score"] != 0
                        else 1.0
                    ),
                    axis=1,
                )
            else:
                merged["val"] = merged["score"]

            cnt_x = merged.groupby(param_x)["test_id"].nunique()
            cnt_y = merged.groupby(param_y)["test_id"].nunique()
            avg_df = merged.groupby([param_y, param_x])["val"].mean().reset_index()
            pivot_df = avg_df.pivot(index=param_y, columns=param_x, values="val")
            pivot_df = pivot_df.sort_index().sort_index(axis=1).astype(float)

            if direction == "minimize":
                if graph_type == "heatmap_rel":
                    color_scale = [[0.0, "#4caf50"], [0.5, "#1e1e1e"], [1.0, "#f44336"]]
                    zmid = 1.0
                else:
                    color_scale = [[0.0, "#4caf50"], [1.0, "#f44336"]]
                    zmid = None
            else:
                if graph_type == "heatmap_rel":
                    color_scale = [[0.0, "#f44336"], [0.5, "#1e1e1e"], [1.0, "#4caf50"]]
                    zmid = 1.0
                else:
                    color_scale = [[0.0, "#f44336"], [1.0, "#4caf50"]]
                    zmid = None

            text_fmt = ".3f" if graph_type == "heatmap_rel" else ".3s"

            vmin = pivot_df.min().min()
            vmax = pivot_df.max().max()
            safe_range = None
            if pd.notna(vmin) and vmin == vmax:
                safe_range = [vmin - 0.1, vmax + 0.1]
                zmid = None

            fig = px.imshow(
                pivot_df.values,
                labels=dict(
                    x=f"{param_x}",
                    y=f"{param_y}",
                    color="Rel Ave" if graph_type == "heatmap_rel" else "Abs Ave",
                ),
                x=[f"{x} (n={cnt_x.get(x, 0)})" for x in pivot_df.columns],
                y=[f"{y} (n={cnt_y.get(y, 0)})" for y in pivot_df.index],
                aspect="auto",
                color_continuous_scale=color_scale,
                color_continuous_midpoint=zmid,
                range_color=safe_range,
                origin="lower",
                text_auto=text_fmt,
            )
            fig.update_layout(
                xaxis_title=f"Parameter: {param_x}", yaxis_title=f"Parameter: {param_y}"
            )
        else:
            fig = px.scatter(title="（パラメータ情報を取得できませんでした）")
            fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")

    elif graph_type == "score_time":
        df_st = df.copy()
        df_st["time"] = pd.to_numeric(df_st["time"], errors="coerce")
        df_st = df_st.dropna(subset=["time"])
        label_order = add_ts_count_label(df_st, sorted_ts)
        fig = px.scatter(
            df_st,
            x="time",
            y="score",
            color="ts_label",
            hover_data=["test_id"],
            category_orders={"ts_label": label_order},
            labels={"ts_label": "timestamp"},
            render_mode="webgl",
        )
        fig.update_layout(xaxis_title="Time (s)", yaxis_title="Score")

    elif graph_type == "regression":
        cmp = store.compare(base_ts, target_ts)
        cmp = cmp.dropna(subset=["base", "target"])
        if cmp.empty:
            fig = px.scatter(title="（比較できるデータがありません）")
            fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        else:
            ascending = direction == "maximize"
            cmp = cmp.sort_values("delta", ascending=ascending)
            if direction == "minimize":
                cmp["判定"] = cmp["delta"].apply(
                    lambda d: "改善" if d < 0 else ("悪化" if d > 0 else "同じ")
                )
            else:
                cmp["判定"] = cmp["delta"].apply(
                    lambda d: "改善" if d > 0 else ("悪化" if d < 0 else "同じ")
                )
            fig = px.bar(
                cmp,
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
            fig.update_xaxes(categoryorder="array", categoryarray=list(cmp["name"]))
            fig.update_layout(xaxis_title="Case", yaxis_title="Δ (Target - Base)")

    is_log = bool(log_scale and "log" in log_scale)

    if graph_type in ["heatmap_abs", "heatmap_rel"]:
        yaxis_type = "category"
        xaxis_type = "category"
    else:
        yaxis_type = "log" if is_log else "linear"
        xaxis_type = None

    fig.update_layout(
        template="plotly_dark",
        hovermode="x unified" if graph_type in ["abs", "rel"] else "closest",
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="#1e1e1e",
        plot_bgcolor="#1e1e1e",
        uirevision=True,
        yaxis_type=yaxis_type,
    )

    if xaxis_type:
        fig.update_layout(xaxis_type=xaxis_type)

    if graph_type == "heatmap_abs":
        summary_msg = f"ヒートマップ対象: {target_ts}"
    elif graph_type == "heatmap_rel":
        summary_msg = f"ヒートマップ対象: {target_ts} (Base: {base_ts})"
    elif graph_type == "regression":
        st = store.paired_stats(base_ts, target_ts)
        p_str = f"{st['p']:.3g}" if st["p"] is not None else "-"
        summary_msg = (
            f"回帰: Target {target_ts} vs Base {base_ts} | "
            f"改善 {st['win']} / 悪化 {st['lose']} / 同 {st['tie']} (n={st['n']}) | "
            f"Wilcoxon p={p_str}"
        )
    else:
        summary_msg = f"直近に選択したケース: {target_ts}"

    return fig, summary_msg
