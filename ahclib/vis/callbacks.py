import pandas as pd
import dash
from dash import ctx
from dash.dependencies import Input, Output, State

from . import figures
from . import tabs
from .data import format_timestamp


def register_callbacks(app, store):
    @app.callback(
        Output("target-ts-store", "data"),
        Output("prev-selected-rows", "data"),
        Input("timestamp-table", "selected_rows"),
        State("prev-selected-rows", "data"),
        State("target-ts-store", "data"),
        State("table-data", "data"),
    )
    def update_target_store(selected_rows, prev_selected, current_target, table_data):
        if selected_rows is None:
            selected_rows = []
        if prev_selected is None:
            prev_selected = []
        if not table_data:
            return None, selected_rows

        added = [r for r in selected_rows if r not in prev_selected]
        new_target = current_target

        if added:
            last_added = added[-1]
            if last_added < len(table_data):
                new_target = table_data[last_added]["timestamp"]
        else:
            selected_ts_list = [
                table_data[r]["timestamp"] for r in selected_rows if r < len(table_data)
            ]
            if new_target not in selected_ts_list:
                if selected_ts_list:
                    new_target = sorted(selected_ts_list)[-1]
                else:
                    new_target = None

        return new_target, selected_rows

    @app.callback(
        Output("sidebar-container", "className"),
        Output("pin-btn", "children"),
        Output("pin-btn", "title"),
        Input("pin-btn", "n_clicks"),
        State("sidebar-container", "className"),
        prevent_initial_call=True,
    )
    def toggle_sidebar_pin(n_clicks, current_class):
        if "sidebar-unpinned" in current_class:
            return "sidebar-base sidebar-pinned", "◀", "サイドバーの固定を解除する"
        else:
            return "sidebar-base sidebar-unpinned", "📌", "サイドバーを固定する"

    @app.callback(
        Output("param-selector-container", "style"),
        Output("param-y-wrapper", "style"),
        Input("graph-type", "value"),
    )
    def toggle_param_selector(graph_type):
        if graph_type in ["heatmap_abs", "heatmap_rel", "difficulty_heatmap"]:
            return {"display": "flex", "alignItems": "center", "gap": "5px"}, {
                "display": "flex",
                "alignItems": "center",
                "gap": "5px",
            }
        elif graph_type in [
            "param_scatter",
            "param_box",
            "param_line",
            "difficulty_box",
        ]:
            return {"display": "flex", "alignItems": "center", "gap": "5px"}, {
                "display": "none"
            }
        return {"display": "none"}, {"display": "none"}

    @app.callback(
        Output("param-selector", "options"),
        Output("param-selector", "value"),
        Output("param-selector-y", "options"),
        Output("param-selector-y", "value"),
        Input("reload-button", "n_clicks"),
        State("param-selector", "value"),
        State("param-selector-y", "value"),
    )
    def update_param_options(n, current_x, current_y):
        meta_df = store.meta()
        cols = [c for c in meta_df.columns if c != "test_id"]
        if not cols:
            return [], None, [], None

        options = [{"label": c, "value": c} for c in cols]

        val_x = current_x if current_x in cols else cols[0]
        val_y = (
            current_y if current_y in cols else (cols[1] if len(cols) > 1 else cols[0])
        )

        return options, val_x, options, val_y

    @app.callback(
        Output("base-store", "data"),
        Input("timestamp-table", "active_cell"),
        State("table-data", "data"),
        State("base-store", "data"),
    )
    def update_base_store(active_cell, table_data, current_base):
        if not active_cell or not table_data:
            return current_base
        if active_cell["column_id"] == "is_base_str":
            base_ts = active_cell.get("row_id")
            if base_ts:
                return base_ts
            row_idx = active_cell["row"]
            if row_idx < len(table_data):
                return table_data[row_idx]["timestamp"]
        return current_base

    @app.callback(
        Output("dummy-output", "children"),
        Input("timestamp-table", "data"),
        State("timestamp-table", "data_previous"),
        prevent_initial_call=True,
    )
    def save_memo(current_data, previous_data):
        if current_data and previous_data:
            for curr, prev in zip(current_data, previous_data):
                c_memo = str(curr.get("memo", "")).strip()
                p_memo = str(prev.get("memo", "")).strip()
                if c_memo != p_memo:
                    store.save_memo(curr["timestamp"], c_memo)
        return dash.no_update

    @app.callback(
        Output("timestamp-table", "data"),
        Output("table-data", "data"),
        Output("timestamp-table", "active_cell"),
        Input("reload-button", "n_clicks"),
        Input("base-store", "data"),
        Input("timestamp-table", "active_cell"),
        Input("auto-refresh-interval", "n_intervals"),
        State("table-data", "data"),
    )
    def update_table(n, base_ts, active_cell, n_intervals, current_data):
        triggered = ctx.triggered_id

        if triggered in ("reload-button", "auto-refresh-interval"):
            store.refresh()

        # 同じセルの連続クリックでも発火させるため active_cell をリセットする
        reset_active = dash.no_update
        if (
            triggered == "timestamp-table"
            and active_cell
            and active_cell.get("column_id") in ("delete_btn", "is_base_str")
        ):
            reset_active = None

        if (
            triggered == "timestamp-table"
            and active_cell
            and active_cell.get("column_id") == "delete_btn"
        ):
            ts_to_delete = active_cell.get("row_id")
            if not ts_to_delete:
                row_idx = active_cell["row"]
                if current_data and row_idx < len(current_data):
                    ts_to_delete = current_data[row_idx]["timestamp"]

            if ts_to_delete:
                store.delete(ts_to_delete)
                store.refresh()

        df = store.long_frame()
        if df.empty:
            return [], [], reset_active

        timestamps = sorted(df["timestamp"].unique())
        if not timestamps:
            return [], [], reset_active

        if base_ts not in timestamps:
            base_ts = timestamps[0]

        base_df = df[df["timestamp"] == base_ts][["test_id", "score"]].rename(
            columns={"score": "base_score"}
        )
        merged = pd.merge(df, base_df, on="test_id", how="left")

        merged["rel_score"] = merged.apply(
            lambda r: (
                r["score"] / r["base_score"]
                if pd.notna(r["base_score"]) and r["base_score"] != 0
                else 1.0
            ),
            axis=1,
        )

        grouped = (
            merged.groupby("timestamp")
            .agg(
                average_score=("score", "mean"),
                rel_ave=("rel_score", "mean"),
                std_score=("score", "std"),
            )
            .reset_index()
        )

        if "state" in df.columns:
            ng_series = df[df["state"] != "AC"].groupby("timestamp").size()
            grouped["ng_cnt"] = (
                grouped["timestamp"].map(ng_series).fillna(0).astype(int)
            )
        else:
            grouped["ng_cnt"] = 0

        grouped["formatted"] = grouped["timestamp"].apply(format_timestamp)
        grouped["is_base_str"] = grouped["timestamp"].apply(
            lambda ts: "★" if ts == base_ts else "・"
        )
        grouped["delete_btn"] = "🗑️"
        grouped["memo"] = grouped["timestamp"].apply(store.get_memo)
        grouped = grouped.sort_values("timestamp")

        records = grouped.to_dict("records")
        for r in records:
            r["id"] = r["timestamp"]

        return records, records, reset_active

    @app.callback(
        Output("timestamp-table", "selected_rows"),
        Input("add-latest", "n_clicks"),
        Input("select-all", "n_clicks"),
        Input("clear-selection", "n_clicks"),
        Input("reload-button", "n_clicks"),
        Input("timestamp-table", "selected_rows"),
        State("table-data", "data"),
    )
    def handle_selection(n_latest, n_all, n_clear, n_reload, native_selected, data):
        triggered = ctx.triggered_id
        if not data:
            return []

        selected = native_selected if native_selected else []
        selected = [s for s in selected if s < len(data)]

        if triggered == "add-latest":
            latest_idx = len(data) - 1
            if latest_idx >= 0 and latest_idx not in selected:
                selected.append(latest_idx)
            return sorted(selected)
        elif triggered == "select-all":
            return list(range(len(data)))
        elif triggered == "clear-selection":
            return []

        return selected

    @app.callback(
        Output("current-timestamp-display", "children"),
        Input("target-ts-store", "data"),
    )
    def show_current_timestamp(target_ts):
        if not target_ts:
            return "テストケース詳細 (選択されていません)"
        return f"詳細表示: {target_ts}"

    @app.callback(
        Output("file-name-table", "data"),
        Input("target-ts-store", "data"),
        Input("base-store", "data"),
        Input("case-filter-check", "value"),
    )
    def update_file_table(target_ts, base_ts, case_filter):
        if not target_ts:
            return []
        df_all = store.long_frame()
        if df_all.empty:
            return []

        df_all["score"] = pd.to_numeric(df_all["score"], errors="coerce")

        if store.direction == "minimize":
            best_df = (
                df_all.groupby("name")["score"]
                .min()
                .reset_index()
                .rename(columns={"score": "best"})
            )
        else:
            best_df = (
                df_all.groupby("name")["score"]
                .max()
                .reset_index()
                .rename(columns={"score": "best"})
            )

        df = df_all[df_all["timestamp"] == target_ts].copy()

        if base_ts:
            base_df = df_all[df_all["timestamp"] == base_ts][["name", "score"]].rename(
                columns={"score": "base_score"}
            )
            df = pd.merge(df, base_df, on="name", how="left")
            df["rel"] = df.apply(
                lambda r: (
                    r["score"] / r["base_score"]
                    if pd.notna(r["base_score"]) and r["base_score"] != 0
                    else 1.0
                ),
                axis=1,
            )
        else:
            df["rel"] = 1.0

        df = pd.merge(df, best_df, on="name", how="left")
        df["time"] = pd.to_numeric(df["time"], errors="coerce")

        if "state" not in df.columns:
            df["state"] = ""
        if case_filter and "non_ac" in case_filter:
            df = df[df["state"] != "AC"]

        records = df[["name", "state", "score", "rel", "best", "time"]].to_dict(
            "records"
        )
        for r in records:
            r["id"] = r["name"]

        return records

    @app.callback(
        Output("file-name-table", "style_data_conditional"),
        Input("file-name-table", "active_cell"),
    )
    def highlight_selected_case_row(active_cell):
        """選択中ケースの行全体をハイライトする"""
        styles = [
            {
                "if": {"filter_query": '{state} != "AC" && {state} != ""'},
                "color": "#e57373",
            },
            {
                "if": {
                    "filter_query": '{state} != "AC" && {state} != ""',
                    "column_id": "state",
                },
                "fontWeight": "bold",
            },
            {
                "if": {"state": "active"},
                "backgroundColor": "#3a3f47",
                "border": "1px solid #444",
            },
        ]
        if active_cell:
            filename = active_cell.get("row_id")
            if filename:
                # ソートされても追従するよう、行番号ではなくケース名で指定する
                styles.append(
                    {
                        "if": {"filter_query": f'{{name}} = "{filename}"'},
                        "backgroundColor": "#3a3f47",
                    }
                )
            else:
                styles.append(
                    {
                        "if": {"row_index": active_cell["row"]},
                        "backgroundColor": "#3a3f47",
                    }
                )
        return styles

    @app.callback(
        Output("score-comparison-graph", "figure"),
        Output("summary-text", "children"),
        Input("timestamp-table", "selected_rows"),
        Input("graph-type", "value"),
        Input("param-selector", "value"),
        Input("param-selector-y", "value"),
        Input("log-scale-check", "value"),
        Input("target-ts-store", "data"),
        State("table-data", "data"),
        State("base-store", "data"),
    )
    def update_graph(
        rows, graph_type, param_x, param_y, log_scale, target_ts, table_data, base_ts
    ):
        return figures.build_graph(
            store,
            rows,
            graph_type,
            param_x,
            param_y,
            log_scale,
            target_ts,
            table_data,
            base_ts,
        )

    @app.callback(
        Output("tab-content", "children"),
        Input("detail-tabs", "value"),
        Input("file-name-table", "active_cell"),
        Input("target-ts-store", "data"),
        State("file-name-table", "data"),
        State("base-store", "data"),
        State("table-data", "data"),
    )
    def render_tab_content(tab, active_cell, target_ts, file_data, base_ts, table_data):
        return tabs.render_tab_content(
            store, tab, active_cell, target_ts, file_data, base_ts, table_data
        )

    @app.callback(
        Output("auto-refresh-interval", "disabled"),
        Input("auto-refresh-check", "value"),
    )
    def toggle_auto_refresh(value):
        return not (value and "on" in value)
