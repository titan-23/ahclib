from typing import Any, Optional

import dash
from dash import Dash, ctx, html
from dash.dependencies import Input, Output, State

from . import config, figures, tabs
from .data import ResultStore
from .table_data import (
    build_case_rows,
    build_run_rows,
    parameter_column_specs,
    selected_row_ids,
)


def _changed_cells(change: Any) -> list[dict[str, Any]]:
    if isinstance(change, dict):
        return [change]
    if isinstance(change, list):
        return [item for item in change if isinstance(item, dict)]
    return []


def _selected_case(selected_rows: Any) -> Optional[dict[str, Any]]:
    if isinstance(selected_rows, list):
        return next((row for row in selected_rows if isinstance(row, dict)), None)
    row_ids = selected_row_ids(selected_rows)
    return {"id": row_ids[0]} if row_ids else None


def adjacent_case_id(
    rows: Optional[list[dict[str, Any]]],
    selected_rows: Any,
    offset: int,
) -> Optional[str]:
    """現在の表示順で隣接するケース ID を返す"""
    row_ids = [str(row["id"]) for row in rows or [] if row.get("id") is not None]
    if not row_ids:
        return None

    selected_ids = selected_row_ids(selected_rows)
    current_id = selected_ids[0] if selected_ids else None
    try:
        current_index = row_ids.index(current_id) if current_id else -1
    except ValueError:
        current_index = -1

    if current_index < 0:
        next_index = 0 if offset > 0 else len(row_ids) - 1
    else:
        next_index = current_index + offset
    return row_ids[min(max(next_index, 0), len(row_ids) - 1)]


def register_callbacks(app: Dash, store: ResultStore) -> None:
    @app.callback(
        Output("target-ts-store", "data"),
        Input("timestamp-table", "selectedRows"),
        Input("timestamp-table", "cellClicked"),
        State("target-ts-store", "data"),
    )
    def update_target_store(selected_rows, clicked_cell, current_target):
        selected_ids = selected_row_ids(selected_rows)
        if ctx.triggered_prop_id == "timestamp-table.cellClicked" and clicked_cell:
            column_id = clicked_cell.get("colId")
            row_id = clicked_cell.get("rowId")
            if row_id is not None and column_id not in ("is_base_str", "delete_btn"):
                return str(row_id)

        if current_target in selected_ids:
            return current_target
        return max(selected_ids) if selected_ids else None

    @app.callback(
        Output("sidebar-container", "className"),
        Output("pin-btn", "children"),
        Output("pin-btn", "title"),
        Input("pin-btn", "n_clicks"),
        State("sidebar-container", "className"),
        prevent_initial_call=True,
    )
    def toggle_sidebar_pin(_click_count, current_class):
        if "sidebar-unpinned" in current_class:
            return "sidebar-base sidebar-pinned", "◀", "サイドバーの固定を解除する"
        return "sidebar-base sidebar-unpinned", "📌", "サイドバーを固定する"

    @app.callback(
        Output("param-selector-container", "style"),
        Output("param-y-wrapper", "style"),
        Input("graph-type", "value"),
    )
    def toggle_param_selector(graph_type):
        visible = {"display": "flex", "alignItems": "center", "gap": "5px"}
        if graph_type in ["heatmap_abs", "heatmap_rel", "difficulty_heatmap"]:
            return visible, visible
        if graph_type in [
            "param_scatter",
            "param_box",
            "param_line",
            "difficulty_box",
        ]:
            return visible, {"display": "none"}
        return {"display": "none"}, {"display": "none"}

    @app.callback(
        Output("param-selector", "options"),
        Output("param-selector", "value"),
        Output("param-selector-y", "options"),
        Output("param-selector-y", "value"),
        Input("reload-button", "n_clicks"),
        Input("result-version-store", "data"),
        State("param-selector", "value"),
        State("param-selector-y", "value"),
    )
    def update_param_options(
        _click_count,
        _result_version,
        current_x,
        current_y,
    ):
        metadata = store.snapshot().metadata
        parameter_columns = [
            column for column in metadata.columns if column != "test_id"
        ]
        if not parameter_columns:
            return [], None, [], None

        options = [{"label": column, "value": column} for column in parameter_columns]
        selected_x = (
            current_x if current_x in parameter_columns else parameter_columns[0]
        )
        selected_y = (
            current_y
            if current_y in parameter_columns
            else (
                parameter_columns[1]
                if len(parameter_columns) > 1
                else parameter_columns[0]
            )
        )
        return options, selected_x, options, selected_y

    @app.callback(
        Output("base-request-store", "data"),
        Input("timestamp-table", "cellClicked"),
        Input("previous-base", "n_clicks"),
        Input("target-ts-store", "data"),
        Input("base-mode-check", "value"),
        prevent_initial_call=True,
    )
    def request_base_change(
        clicked_cell,
        _previous_clicks,
        target_timestamp,
        base_mode,
    ):
        if (
            ctx.triggered_prop_id == "timestamp-table.cellClicked"
            and clicked_cell
            and clicked_cell.get("colId") == "is_base_str"
        ):
            return {
                "timestamp": clicked_cell.get("rowId"),
                "clicked_at": clicked_cell.get("timestamp"),
            }
        use_previous = ctx.triggered_id == "previous-base" or (
            ctx.triggered_id in ("target-ts-store", "base-mode-check")
            and base_mode
            and "previous" in base_mode
        )
        if use_previous and target_timestamp:
            timestamps = sorted(
                store.snapshot().results["timestamp"].dropna().astype(str).unique()
            )
            if target_timestamp in timestamps:
                index = timestamps.index(target_timestamp)
                return {"timestamp": timestamps[max(0, index - 1)]}
        return dash.no_update

    @app.callback(
        Output("pending-delete-store", "data"),
        Output("delete-confirm", "displayed"),
        Output("delete-confirm", "message"),
        Input("timestamp-table", "cellClicked"),
        prevent_initial_call=True,
    )
    def request_delete(clicked_cell):
        if not clicked_cell or clicked_cell.get("colId") != "delete_btn":
            return dash.no_update, dash.no_update, dash.no_update
        timestamp = clicked_cell.get("rowId")
        if not timestamp:
            return dash.no_update, dash.no_update, dash.no_update
        return str(timestamp), True, f"実行結果 {timestamp} を削除しますか"

    @app.callback(
        Output("delete-result-store", "data"),
        Input("delete-confirm", "submit_n_clicks"),
        State("pending-delete-store", "data"),
        prevent_initial_call=True,
    )
    def delete_result(_submit_count, timestamp):
        if not timestamp:
            return dash.no_update
        try:
            store.delete(str(timestamp))
            store.refresh()
            return {"timestamp": str(timestamp), "error": None}
        except (OSError, ValueError) as error:
            return {"timestamp": str(timestamp), "error": str(error)}

    @app.callback(
        Output("run-edit-result-store", "data"),
        Input("timestamp-table", "cellValueChanged"),
        Input("timestamp-table", "cellClicked"),
        prevent_initial_call=True,
    )
    def save_run_edit(change, clicked_cell):
        try:
            if (
                ctx.triggered_prop_id == "timestamp-table.cellClicked"
                and clicked_cell
                and clicked_cell.get("colId") == "favorite_str"
            ):
                timestamp = str(clicked_cell.get("rowId") or "")
                store.toggle_favorite(timestamp)
                return {"timestamp": timestamp, "error": None}

            saved_timestamps = []
            for changed_cell in _changed_cells(change):
                column_id = changed_cell.get("colId")
                if column_id not in ("memo", "tag"):
                    continue
                row = changed_cell.get("data") or {}
                timestamp = row.get("timestamp") or changed_cell.get("rowId")
                if not timestamp:
                    continue
                new_value = changed_cell.get("newValue")
                value = "" if new_value is None else str(new_value)
                if column_id == "memo":
                    store.save_memo(str(timestamp), value)
                else:
                    store.save_tag(str(timestamp), value)
                saved_timestamps.append(str(timestamp))
            if saved_timestamps:
                return {"timestamp": saved_timestamps[-1], "error": None}
        except (OSError, PermissionError, ValueError) as error:
            return {"timestamp": None, "error": str(error)}
        return dash.no_update

    @app.callback(
        Output("timestamp-table", "rowData"),
        Output("table-data", "data"),
        Output("result-version-store", "data"),
        Output("base-store", "data"),
        Input("reload-button", "n_clicks"),
        Input("base-request-store", "data"),
        Input("auto-refresh-interval", "n_intervals"),
        Input("delete-result-store", "data"),
        Input("run-edit-result-store", "data"),
        State("result-version-store", "data"),
        State("base-store", "data"),
    )
    def update_table(
        _reload_clicks,
        base_request,
        _interval_count,
        _delete_result,
        _run_edit_result,
        previous_version,
        current_base,
    ):
        triggered = ctx.triggered_prop_id
        if triggered == "reload-button.n_clicks":
            store.refresh()

        snapshot = store.snapshot()
        if (
            triggered == "auto-refresh-interval.n_intervals"
            and snapshot.version == previous_version
        ):
            return (
                dash.no_update,
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        requested_base = (
            base_request.get("timestamp")
            if triggered == "base-request-store.data" and base_request
            else current_base
        )
        rows, actual_base = build_run_rows(
            snapshot.results,
            requested_base,
            store.get_memo,
            run_summary=snapshot.run_summary,
            run_annotations=store.run_annotations(snapshot.run_indices),
        )
        return rows, rows, snapshot.version, actual_base

    @app.callback(
        Output("status-banner", "children"),
        Output("status-banner", "style"),
        Input("result-version-store", "data"),
        Input("delete-result-store", "data"),
        Input("run-edit-result-store", "data"),
        Input("case-edit-result-store", "data"),
    )
    def show_status(
        _result_version,
        delete_result,
        run_edit_result,
        case_edit_result,
    ):
        warnings = list(store.snapshot().warnings)
        for label, result in [
            ("削除", delete_result),
            ("実行情報の保存", run_edit_result),
            ("ケース情報の保存", case_edit_result),
        ]:
            if result and result.get("error"):
                warnings.append(f"{label}失敗 ({result['error']})")
        if not warnings:
            return "", {"display": "none"}

        shown = warnings[:6]
        if len(warnings) > len(shown):
            shown.append(f"ほか {len(warnings) - len(shown)} 件")
        return (
            html.Ul([html.Li(warning) for warning in shown]),
            {
                "display": "block",
                "backgroundColor": "#4a3516",
                "color": "#ffd180",
                "padding": "6px 20px",
                "margin": "0",
                "fontSize": "12px",
            },
        )

    @app.callback(
        Output("timestamp-table", "selectedRows"),
        Input("add-latest", "n_clicks"),
        Input("select-all", "n_clicks"),
        Input("clear-selection", "n_clicks"),
        State("timestamp-table", "selectedRows"),
        State("table-data", "data"),
        prevent_initial_call=True,
    )
    def handle_selection(
        _latest_clicks,
        _select_all_clicks,
        _clear_clicks,
        current_selection,
        table_data,
    ):
        available_ids = [str(row["id"]) for row in table_data or []]
        if not available_ids or ctx.triggered_id == "clear-selection":
            return []
        if ctx.triggered_id == "select-all":
            return {"ids": available_ids}

        selected_ids = [
            row_id
            for row_id in selected_row_ids(current_selection)
            if row_id in available_ids
        ]
        if ctx.triggered_id == "add-latest":
            latest = max(available_ids)
            if latest not in selected_ids:
                selected_ids.append(latest)
        return {"ids": selected_ids}

    @app.callback(
        Output("current-timestamp-display", "children"),
        Input("target-ts-store", "data"),
    )
    def show_current_timestamp(target_timestamp):
        if not target_timestamp:
            return "テストケース詳細 (選択されていません)"
        return f"詳細表示: {target_timestamp}"

    @app.callback(
        Output("file-name-table", "rowData"),
        Input("target-ts-store", "data"),
        Input("base-store", "data"),
        Input("case-filter-check", "value"),
        Input("result-version-store", "data"),
        Input("case-edit-result-store", "data"),
    )
    def update_file_rows(
        target_timestamp,
        base_timestamp,
        case_filter,
        _result_version,
        _case_edit_result,
    ):
        snapshot = store.snapshot()
        filters = list(case_filter or [])
        return build_case_rows(
            snapshot.results,
            target_timestamp,
            base_timestamp,
            store.direction,
            metadata=snapshot.metadata,
            non_accepted_only="non_ac" in filters,
            comparison_filters=[value for value in filters if value != "non_ac"],
            annotations=store.case_annotations(target_timestamp),
        )

    @app.callback(
        Output("case-edit-result-store", "data"),
        Input("file-name-table", "cellValueChanged"),
        Input("file-name-table", "cellClicked"),
        State("target-ts-store", "data"),
        prevent_initial_call=True,
    )
    def save_case_edit(change, clicked_cell, target_timestamp):
        if not target_timestamp:
            return dash.no_update
        try:
            if (
                ctx.triggered_prop_id == "file-name-table.cellClicked"
                and clicked_cell
                and clicked_cell.get("colId") == "bookmark_str"
            ):
                case_id = str(clicked_cell.get("rowId") or "")
                store.toggle_case_bookmark(str(target_timestamp), case_id)
                return {"case_id": case_id, "error": None}

            saved_case_ids = []
            for changed_cell in _changed_cells(change):
                if changed_cell.get("colId") != "case_memo":
                    continue
                case_id = str(changed_cell.get("rowId") or "")
                new_value = changed_cell.get("newValue")
                memo = "" if new_value is None else str(new_value)
                store.save_case_memo(str(target_timestamp), case_id, memo)
                saved_case_ids.append(case_id)
            if saved_case_ids:
                return {"case_id": saved_case_ids[-1], "error": None}
        except (OSError, PermissionError, ValueError) as error:
            return {"case_id": None, "error": str(error)}
        return dash.no_update

    @app.callback(
        Output("file-name-table", "columnDefs"),
        Input("result-version-store", "data"),
        Input("case-column-groups", "value"),
    )
    def update_file_columns(_result_version, visible_groups):
        metadata = store.snapshot().metadata
        return config.case_column_defs(
            store.direction,
            parameter_column_specs(metadata),
            visible_groups=visible_groups,
            read_only=store.read_only,
        )

    @app.callback(
        Output("file-name-table", "filterModel"),
        Output("case-filter-check", "value"),
        Input("clear-case-filters", "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_case_filters(_click_count):
        return {}, []

    @app.callback(
        Output("file-name-table", "selectedRows"),
        Output("file-name-table", "scrollTo"),
        Input("previous-case", "n_clicks"),
        Input("next-case", "n_clicks"),
        State("file-name-table", "virtualRowData"),
        State("file-name-table", "rowData"),
        State("file-name-table", "selectedRows"),
        prevent_initial_call=True,
    )
    def move_case(
        _previous_clicks,
        _next_clicks,
        visible_rows,
        all_rows,
        selected_rows,
    ):
        rows = visible_rows if visible_rows is not None else all_rows
        offset = -1 if ctx.triggered_id == "previous-case" else 1
        row_id = adjacent_case_id(rows, selected_rows, offset)
        if row_id is None:
            return dash.no_update, dash.no_update
        return {"ids": [row_id]}, {"rowId": row_id, "rowPosition": "middle"}

    @app.callback(
        Output("score-comparison-graph", "figure"),
        Output("summary-text", "children"),
        Input("timestamp-table", "selectedRows"),
        Input("graph-type", "value"),
        Input("param-selector", "value"),
        Input("param-selector-y", "value"),
        Input("log-scale-check", "value"),
        Input("graph-reset", "n_clicks"),
        Input("target-ts-store", "data"),
        Input("result-version-store", "data"),
        State("base-store", "data"),
    )
    def update_graph(
        selected_rows,
        graph_type,
        param_x,
        param_y,
        log_scale,
        reset_count,
        target_timestamp,
        _result_version,
        base_timestamp,
    ):
        snapshot = store.snapshot()
        return figures.build_graph(
            store,
            snapshot,
            selected_row_ids(selected_rows),
            graph_type,
            param_x,
            param_y,
            log_scale,
            target_timestamp,
            base_timestamp,
            reset_count=reset_count or 0,
        )

    @app.callback(
        Output("tab-content", "children"),
        Output("detail-search-result", "children"),
        Input("detail-tabs", "value"),
        Input("file-name-table", "selectedRows"),
        Input("target-ts-store", "data"),
        Input("result-version-store", "data"),
        Input("detail-search", "value"),
        Input("detail-view-options", "value"),
        State("base-store", "data"),
    )
    def render_tab_content(
        tab,
        selected_rows,
        target_timestamp,
        _result_version,
        search,
        view_options,
        base_timestamp,
    ):
        snapshot = store.snapshot()
        return tabs.render_tab_content(
            store,
            snapshot,
            tab,
            _selected_case(selected_rows),
            target_timestamp,
            base_timestamp,
            search=search,
            view_options=view_options,
        )

    @app.callback(
        Output("auto-refresh-interval", "disabled"),
        Input("auto-refresh-check", "value"),
    )
    def toggle_auto_refresh(value):
        return not (value and "on" in value)
