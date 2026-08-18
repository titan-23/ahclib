from bisect import bisect_left, bisect_right
import json
import os
import time
from typing import Callable

import dash
import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback_context, dcc, html
from dash.development.base_component import Component

from .config import (
    BASE_STYLESHEET,
    DARK_THEME,
    tab_selected_style,
    tab_style,
)
from .data import compute_compact_layout, load_and_process_data
from .store import BeamStore


def create_app(
    generate_board_visual: Callable[[str], Component],
    history_path: str = "history.json",
) -> dash.Dash:
    store = BeamStore(history_path, generate_board_visual)

    cyto.load_extra_layouts()

    assets_folder = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets"
    )

    app = dash.Dash(
        __name__,
        assets_folder=assets_folder,
        update_title=None,
        suppress_callback_exceptions=True,
    )
    app._ahclib_beam_store = store

    app.layout = html.Div(
        style={
            "backgroundColor": DARK_THEME["background"],
            "color": DARK_THEME["text"],
            "height": "100vh",
            "display": "flex",
            "flexDirection": "column",
            "fontFamily": "sans-serif",
        },
        children=[
            dcc.Store(id="full-data-store"),
            dcc.Store(id="collapsed-nodes-store", data=[]),
            dcc.Store(id="bookmark-nodes-store", data=[]),
            dcc.Store(id="clicked-child-store", data=None),
            dcc.Interval(id="auto-play-interval", interval=1000, disabled=True),
            dcc.Store(id="show-goal-path-store", data=False),
            html.Div(
                style={
                    "padding": "10px",
                    "borderBottom": f'1px solid {DARK_THEME["border"]}',
                    "backgroundColor": DARK_THEME["panel"],
                    "display": "flex",
                    "gap": "15px",
                    "alignItems": "center",
                },
                children=[
                    html.Div(
                        style={"flex": "1", "minWidth": "250px"},
                        children=[
                            html.Label(
                                "表示ターン区間:",
                                style={"fontWeight": "bold", "fontSize": "12px"},
                            ),
                            dcc.RangeSlider(
                                id="turn-range-slider",
                                min=0,
                                max=1,
                                step=1,
                                value=[0, 1],
                                marks=None,
                                tooltip={"placement": "bottom", "always_visible": True},
                            ),
                        ],
                    ),
                    html.Div(
                        children=[
                            html.Button(
                                "再読み込み",
                                id="reload-button",
                                className="modern-btn",
                                style={
                                    "marginRight": "10px",
                                    "backgroundColor": "#4caf50",
                                },
                            ),
                            html.Button(
                                "再生",
                                id="play-button",
                                n_clicks=0,
                                className="modern-btn",
                            ),
                        ]
                    ),
                    html.Div(
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "width": "160px",
                            "marginLeft": "15px",
                        },
                        children=[
                            html.Label(
                                "速度:",
                                style={
                                    "fontWeight": "bold",
                                    "fontSize": "12px",
                                    "marginRight": "5px",
                                },
                            ),
                            html.Div(
                                style={"flex": "1"},
                                children=[
                                    dcc.Slider(
                                        id="playback-speed-slider",
                                        min=1,
                                        max=10,
                                        step=1,
                                        value=4,
                                        marks=None,
                                        tooltip={
                                            "placement": "bottom",
                                            "always_visible": False,
                                        },
                                    )
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        children=[
                            dcc.Input(
                                id="search-input",
                                placeholder="スコア / Action / Hash 検索...",
                                style={"padding": "5px"},
                            ),
                            html.Button(
                                "検索",
                                id="search-button",
                                className="modern-btn",
                                style={"marginLeft": "5px"},
                            ),
                        ]
                    ),
                    html.Div(
                        children=[
                            dcc.Checklist(
                                id="visibility-toggle",
                                options=[
                                    {
                                        "label": " 破棄・無効ノード表示",
                                        "value": "show_pruned",
                                    },
                                    {
                                        "label": " スコアヒートマップ",
                                        "value": "heatmap",
                                    },
                                    {"label": " コンパクト", "value": "compact"},
                                ],
                                value=[],
                                style={"fontSize": "13px"},
                            )
                        ]
                    ),
                    html.Div(
                        children=[
                            dcc.RadioItems(
                                id="tree-direction-toggle",
                                options=[
                                    {"label": " 横(LR) ", "value": "LR"},
                                    {"label": " 縦(TB) ", "value": "TB"},
                                ],
                                value="LR",
                                inline=True,
                                style={
                                    "display": "flex",
                                    "gap": "10px",
                                    "marginLeft": "10px",
                                    "fontWeight": "bold",
                                    "fontSize": "13px",
                                },
                            )
                        ]
                    ),
                    html.Div(
                        children=[
                            html.Button(
                                "破棄ノード一括折畳/展開",
                                id="fold-all-pruned-button",
                                className="modern-btn",
                                style={
                                    "backgroundColor": "#f57c00",
                                    "fontSize": "12px",
                                    "padding": "5px 10px",
                                    "marginLeft": "10px",
                                },
                            ),
                            html.Button(
                                "🏁 ゴール経路強調",
                                id="highlight-goal-button",
                                className="modern-btn",
                                style={
                                    "backgroundColor": "#e91e63",
                                    "fontSize": "12px",
                                    "padding": "5px 10px",
                                    "marginLeft": "10px",
                                },
                            ),
                        ]
                    ),
                    html.Div(
                        id="hover-action-output",
                        style={
                            "marginLeft": "auto",
                            "fontWeight": "bold",
                            "color": DARK_THEME["highlight"],
                            "minWidth": "150px",
                        },
                    ),
                ],
            ),
            html.Div(
                style={
                    "display": "flex",
                    "flex": "1",
                    "overflow": "hidden",
                    "position": "relative",
                },
                children=[
                    html.Div(
                        id="left-panel-container",
                        style={
                            "flex": "1",
                            "display": "flex",
                            "flexDirection": "column",
                            "transition": "flex 0.3s ease",
                        },
                        children=[
                            dcc.Tabs(
                                id="left-tabs",
                                value="tab-tree",
                                children=[
                                    dcc.Tab(
                                        label="探索木",
                                        value="tab-tree",
                                        style=tab_style,
                                        selected_style=tab_selected_style,
                                        children=[
                                            html.Div(
                                                style={
                                                    "position": "relative",
                                                    "width": "100%",
                                                    "height": "calc(100vh - 150px)",
                                                },
                                                children=[
                                                    html.Button(
                                                        "🔍 全体を表示",
                                                        id="fit-button",
                                                        className="modern-btn",
                                                        style={
                                                            "position": "absolute",
                                                            "top": "10px",
                                                            "right": "10px",
                                                            "zIndex": "1000",
                                                            "backgroundColor": "#8e24aa",
                                                            "padding": "6px 12px",
                                                        },
                                                    ),
                                                    cyto.Cytoscape(
                                                        id="cytoscape-tree",
                                                        layout={
                                                            "name": "dagre",
                                                            "rankDir": "LR",
                                                            "nodeSep": 5,
                                                            "rankSep": 40,
                                                            "spacingFactor": 0.8,
                                                            "animate": False,
                                                            "fit": True,
                                                        },
                                                        style={
                                                            "width": "100%",
                                                            "height": "100%",
                                                        },
                                                        stylesheet=BASE_STYLESHEET,
                                                        elements=[],
                                                        zoom=1.0,
                                                        minZoom=0.02,
                                                        maxZoom=5.0,
                                                        autoungrabify=True,
                                                        wheelSensitivity=0.2,
                                                    ),
                                                ],
                                            )
                                        ],
                                    ),
                                    dcc.Tab(
                                        label="全体スコア推移",
                                        value="tab-all-graph",
                                        style=tab_style,
                                        selected_style=tab_selected_style,
                                        children=[
                                            dcc.Graph(
                                                id="all-paths-graph",
                                                style={"height": "calc(100vh - 150px)"},
                                            )
                                        ],
                                    ),
                                    dcc.Tab(
                                        label="ターン統計",
                                        value="tab-stats",
                                        style=tab_style,
                                        selected_style=tab_selected_style,
                                        children=[
                                            html.Div(
                                                id="turn-stats-container",
                                                style={
                                                    "height": "calc(100vh - 150px)",
                                                    "overflowY": "auto",
                                                    "padding": "10px",
                                                },
                                            )
                                        ],
                                    ),
                                ],
                            )
                        ],
                    ),
                    html.Div(
                        id="right-panel-container",
                        className="right-panel right-panel-pinned",
                        children=[
                            html.Div(
                                id="right-panel-toggle-btn",
                                className="panel-toggle-btn",
                                style={"display": "none"},
                                children="◀",
                            ),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "justifyContent": "space-between",
                                    "alignItems": "center",
                                    "backgroundColor": "#2d2d30",
                                    "padding": "5px 10px",
                                    "borderBottom": "1px solid #1e1e1e",
                                },
                                children=[
                                    html.Span(
                                        "詳細パネル",
                                        style={
                                            "fontWeight": "bold",
                                            "fontSize": "12px",
                                            "color": "#aaa",
                                        },
                                    ),
                                    html.Button(
                                        "📌 ピン留め解除",
                                        id="pin-toggle-btn",
                                        style={
                                            "background": "none",
                                            "border": "none",
                                            "color": "#ccc",
                                            "cursor": "pointer",
                                            "fontSize": "12px",
                                            "fontWeight": "bold",
                                        },
                                    ),
                                ],
                            ),
                            html.Div(
                                style={
                                    "padding": "10px",
                                    "flex": "1",
                                    "overflowY": "auto",
                                },
                                children=[
                                    dcc.Tabs(
                                        id="info-tabs",
                                        value="tab-detail",
                                        children=[
                                            dcc.Tab(
                                                label="詳細",
                                                value="tab-detail",
                                                style=tab_style,
                                                selected_style=tab_selected_style,
                                                children=[
                                                    html.Div(
                                                        style={"marginTop": "15px"},
                                                        children=[
                                                            html.Button(
                                                                "枝を折畳む/展開",
                                                                id="toggle-fold-button",
                                                                className="modern-btn",
                                                            ),
                                                            html.Button(
                                                                "⭐ ブックマークに追加",
                                                                id="toggle-bookmark-button",
                                                                className="modern-btn",
                                                                style={
                                                                    "marginLeft": "10px",
                                                                    "backgroundColor": DARK_THEME[
                                                                        "bookmark"
                                                                    ],
                                                                    "color": "#000",
                                                                },
                                                            ),
                                                            html.Div(
                                                                id="node-detail-output",
                                                                style={
                                                                    "marginTop": "15px"
                                                                },
                                                            ),
                                                            html.Label(
                                                                "Action Path:",
                                                                style={
                                                                    "fontWeight": "bold",
                                                                    "marginTop": "15px",
                                                                    "display": "block",
                                                                },
                                                            ),
                                                            html.Div(
                                                                style={
                                                                    "position": "relative"
                                                                },
                                                                children=[
                                                                    dcc.Textarea(
                                                                        id="action-path-output",
                                                                        readOnly=True,
                                                                        placeholder="根からこのノードまでの操作列",
                                                                        style={
                                                                            "width": "100%",
                                                                            "height": "80px",
                                                                            "backgroundColor": "#1e1e1e",
                                                                            "color": "#d4d4d4",
                                                                            "border": f'1px solid {DARK_THEME["border"]}',
                                                                            "borderRadius": "4px",
                                                                            "fontFamily": "monospace",
                                                                            "padding": "8px",
                                                                            "paddingRight": "35px",
                                                                            "resize": "none",
                                                                        },
                                                                    ),
                                                                    dcc.Clipboard(
                                                                        target_id="action-path-output",
                                                                        title="コピー",
                                                                        style={
                                                                            "position": "absolute",
                                                                            "top": "8px",
                                                                            "right": "8px",
                                                                            "color": "#d4d4d4",
                                                                            "cursor": "pointer",
                                                                            "fontSize": "20px",
                                                                        },
                                                                    ),
                                                                ],
                                                            ),
                                                        ],
                                                    )
                                                ],
                                            ),
                                            dcc.Tab(
                                                label="ブックマーク",
                                                value="tab-bookmark",
                                                style=tab_style,
                                                selected_style=tab_selected_style,
                                                children=[
                                                    html.Div(
                                                        id="bookmark-list-output",
                                                        style={"marginTop": "15px"},
                                                    )
                                                ],
                                            ),
                                            dcc.Tab(
                                                label="スコア推移",
                                                value="tab-score",
                                                style=tab_style,
                                                selected_style=tab_selected_style,
                                                children=[
                                                    dcc.Graph(
                                                        id="score-history-graph",
                                                        config={
                                                            "displayModeBar": False
                                                        },
                                                        style={"marginTop": "15px"},
                                                    )
                                                ],
                                            ),
                                            dcc.Tab(
                                                label="盤面状態",
                                                value="tab-state",
                                                style=tab_style,
                                                selected_style=tab_selected_style,
                                                children=[
                                                    html.Div(
                                                        id="node-state-output",
                                                        style={
                                                            "marginTop": "10px",
                                                            "backgroundColor": "#1e1e1e",
                                                            "border": f'1px solid {DARK_THEME["border"]}',
                                                            "minHeight": "100px",
                                                        },
                                                    )
                                                ],
                                            ),
                                        ],
                                        style={"height": "44px"},
                                    )
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            dcc.Markdown(id="keyboard-manager", children=""),
        ],
    )

    @app.callback(
        Output("full-data-store", "data"),
        Output("turn-range-slider", "max"),
        Output("turn-range-slider", "marks"),
        Input("reload-button", "n_clicks"),
        Input("keyboard-manager", "children"),
    )
    def load_data(n_clicks, _):
        # ファイルが変わっていなければ前回の処理結果を使う
        try:
            file_status = os.stat(store.history_path)
            file_signature = (file_status.st_mtime_ns, file_status.st_size)
        except OSError:
            file_signature = None
        if (
            file_signature is not None
            and store.file_signature == file_signature
            and store.processed
        ):
            return {"ts": time.time()}, store.max_turn, None
        processed, max_turn, _ = load_and_process_data(store.history_path)
        store.replace(processed, max_turn, file_signature)
        return {"ts": time.time()}, max_turn, None

    @app.callback(
        Output("turn-range-slider", "value"),
        Output("play-button", "children"),
        Output("auto-play-interval", "disabled"),
        Input("play-button", "n_clicks"),
        Input("auto-play-interval", "n_intervals"),
        State("turn-range-slider", "value"),
        State("turn-range-slider", "max"),
        prevent_initial_call=True,
    )
    def handle_play(n_clicks, n_intervals, current_range, max_t):
        trigger = callback_context.triggered[0]["prop_id"]
        if "play-button" in trigger:
            is_disabled = n_clicks % 2 == 0
            return current_range, "再生" if is_disabled else "停止", is_disabled
        if "auto-play-interval" in trigger:
            new_max = current_range[1] + 1
            if new_max > max_t:
                return [current_range[0], current_range[1]], "再生", True
            return [current_range[0], new_max], "停止", False
        return current_range, "再生", True

    @app.callback(
        Output("cytoscape-tree", "elements"),
        Output("cytoscape-tree", "layout"),
        Input("full-data-store", "data"),
        Input("turn-range-slider", "value"),
        Input("visibility-toggle", "value"),
        Input("collapsed-nodes-store", "data"),
        Input("bookmark-nodes-store", "data"),
        Input("search-button", "n_clicks"),
        Input("left-tabs", "value"),
        Input("tree-direction-toggle", "value"),
        Input("fit-button", "n_clicks"),
        State("search-input", "value"),
        State("cytoscape-tree", "elements"),
    )
    def update_elements(
        store_signal,
        turn_range,
        visibility,
        collapsed_ids,
        bookmarked_ids,
        n_search,
        left_tab,
        tree_direction,
        n_fit,
        search_query,
        current_elements,
    ):
        if left_tab != "tab-tree":
            return dash.no_update, dash.no_update

        trigger = (
            callback_context.triggered[0]["prop_id"]
            if callback_context.triggered
            else ""
        )
        do_fit = trigger in ["fit-button.n_clicks", "full-data-store.data", ""]

        layout_config = {
            "name": "preset",
            "animate": False,
            "fit": do_fit,
            "padding": 30,
            "refresh": time.time(),
        }

        if trigger == "fit-button.n_clicks" and current_elements:
            return current_elements, layout_config

        processed = store.processed
        nodes = processed.get("current_data", {}).get("nodes", [])
        if not nodes:
            return [], dash.no_update

        # 同じ入力の描画要素を再利用し、件数が上限に達したら破棄する
        cache_key = (
            tuple(turn_range),
            tuple(sorted(visibility or [])),
            tuple(sorted(collapsed_ids or [])),
            tuple(sorted(bookmarked_ids or [])),
            tree_direction,
            search_query or "",
        )
        cached_elements = store.elements_cache.get(cache_key)
        if cached_elements is not None:
            return cached_elements, layout_config

        nodes_dict = processed.get("nodes_dict", {})
        children_dict = processed.get("children_dict", {})
        snapshots_dict = processed.get("snapshots_dict", {})
        turn_stats = processed.get("turn_stats", {})
        base_positions = processed.get("base_positions", {})
        inf_value = processed.get("current_data", {}).get("INF", 1e18)

        minimum_turn, maximum_turn = turn_range

        active_turns = processed.get("active_turns", ())
        active_turn_index = bisect_right(active_turns, maximum_turn) - 1
        if active_turn_index >= 0 and active_turns[active_turn_index] >= minimum_turn:
            latest_active_turn = active_turns[active_turn_index]
            active_nodes = snapshots_dict[latest_active_turn]["active"]
            terminal_ids = {str(node_id) for node_id in active_nodes}
        else:
            latest_active_turn = minimum_turn - 1
            terminal_ids = set()

        # 最後に生存ノードがあるターンから根までの経路を再利用する
        active_path = store.active_path_cache.get(latest_active_turn)
        if active_path is None:
            active_path = set()
            for node_id in terminal_ids:
                active_path.update(store.node_path(node_id).node_ids)
            active_path.add("-1")
            store.active_path_cache[latest_active_turn] = active_path

        compact_mode = "compact" in visibility
        positions_map = base_positions
        if compact_mode and active_path:
            compact_cache_key = latest_active_turn
            compact_positions = store.compact_layout_cache.get(compact_cache_key)
            if compact_positions is None:
                raw_positions = compute_compact_layout(
                    active_path, children_dict, nodes_dict, root_id="-1"
                )
                compact_positions = {}
                for node_id, horizontal_position in raw_positions.items():
                    if node_id == "-1":
                        depth = 0
                    elif node_id in nodes_dict:
                        depth = nodes_dict[node_id]["turn"]
                    else:
                        depth = 0
                    compact_positions[node_id] = {
                        "depth": depth,
                        "breadth_center": horizontal_position,
                    }
                store.compact_layout_cache[compact_cache_key] = compact_positions
            positions_map = compact_positions

        collapsed_set = set(collapsed_ids or [])
        bookmarked_set = set(bookmarked_ids or [])
        # 折り畳んだノードの子孫だけを隠す
        hidden_ids = set()
        for collapsed_id in collapsed_set:
            hidden_ids.update(store.subtree(collapsed_id).node_ids)

        show_pruned = "show_pruned" in visibility and not compact_mode
        use_heatmap = "heatmap" in visibility

        if tree_direction == "TB":
            depth_gap = 200
            breadth_gap = 100
        else:
            depth_gap = 300
            breadth_gap = 60

        default_pos = {"depth": 0, "breadth_center": 0.0}
        start_position = positions_map.get("-1", default_pos)
        start_x = (
            start_position["breadth_center"] * breadth_gap
            if tree_direction == "TB"
            else start_position["depth"] * depth_gap
        )
        start_y = (
            start_position["depth"] * depth_gap
            if tree_direction == "TB"
            else start_position["breadth_center"] * breadth_gap
        )

        elements = [
            {
                "data": {"id": "-1", "label": "Start"},
                "classes": "status-active",
                "position": {"x": start_x, "y": start_y},
            }
        ]

        visible_ids = set()
        nodes_by_turn = processed.get("nodes_by_turn", {})
        node_turns = processed.get("node_turns", ())
        first_turn_index = bisect_left(node_turns, minimum_turn)
        last_turn_index = bisect_right(node_turns, maximum_turn)
        for turn in node_turns[first_turn_index:last_turn_index]:
            for node in nodes_by_turn[turn]:
                node_id = node["sid"]
                if node_id in hidden_ids:
                    continue
                if not show_pruned and node_id not in active_path:
                    continue
                visible_ids.add(node_id)
                current_parent_id = node["spid"]
                while (
                    current_parent_id != "-1" and current_parent_id not in visible_ids
                ):
                    if (
                        current_parent_id in nodes_dict
                        and nodes_dict[current_parent_id]["turn"] < minimum_turn
                    ):
                        visible_ids.add(current_parent_id)
                        current_parent_id = nodes_dict[current_parent_id]["spid"]
                    else:
                        break

        visible_nodes = [
            nodes_dict[node_id] for node_id in visible_ids if node_id in nodes_dict
        ]
        visible_nodes.sort(
            key=lambda node: (
                node["turn"],
                node["parent_id"],
                node["score"],
            )
        )

        valid_ids = {"-1"}
        for node in visible_nodes:
            node_id = node["sid"]
            valid_ids.add(node_id)

            if node.get("is_answer", False):
                classes = "status-answer"
            elif node["status"] == 2:
                classes = "status-invalid"
            elif node_id in active_path:
                classes = "status-active"
            else:
                classes = "status-pruned"

            # 破棄ノードと無効ノードは文字を表示しない
            has_text = classes == "status-active" or classes == "status-answer"

            if node_id in collapsed_set:
                classes += " folded"
            if node_id in bookmarked_set:
                classes += " bookmarked"

            if search_query and (
                search_query in str(node["score"])
                or search_query in node.get("action", "")
                or search_query in str(node.get("hash", ""))
            ):
                classes += " searched"

            if node["turn"] < minimum_turn:
                classes += " out-of-range"

            element_data = {"id": node_id}
            if has_text:
                element_data["label"] = node["label"]
            element = {"data": element_data, "classes": classes}

            position = positions_map.get(node_id, default_pos)
            if tree_direction == "TB":
                element["position"] = {
                    "x": position["breadth_center"] * breadth_gap,
                    "y": position["depth"] * depth_gap,
                }
            else:
                element["position"] = {
                    "x": position["depth"] * depth_gap,
                    "y": position["breadth_center"] * breadth_gap,
                }

            if use_heatmap:
                element["data"]["bg_color"] = node["heatmap_color"]
                element["classes"] += " heatmap-node"

            elements.append(element)

        for node in visible_nodes:
            node_id = node["sid"]
            parent_id = node["spid"]
            if parent_id in valid_ids:
                elements.append(
                    {
                        "data": {
                            "id": f"e{parent_id}_{node_id}",
                            "source": parent_id,
                            "target": node_id,
                            "action": node.get("action", ""),
                        }
                    }
                )
            elif node_id != "-1":
                elements.append(
                    {
                        "data": {
                            "id": f"e_start_{node_id}",
                            "source": "-1",
                            "target": node_id,
                            "action": "(省略)",
                        },
                        "classes": "dummy-edge",
                    }
                )

        layout_config = {
            "name": "preset",
            "animate": False,
            "fit": do_fit,
            "padding": 30,
            "refresh": time.time(),
        }

        store.elements_cache[cache_key] = elements
        return elements, layout_config

    @app.callback(
        Output("turn-stats-container", "children"),
        Input("full-data-store", "data"),
        Input("left-tabs", "value"),
    )
    def update_turn_stats(_store_signal, left_tab):
        # 統計タブを開いている時だけ図を作る
        if left_tab != "tab-stats":
            return dash.no_update
        processed = store.processed
        if not processed:
            return html.Div("データがありません", style={"padding": "20px"})
        if store.turn_stats_content is not None:
            return store.turn_stats_content

        turn_stats = processed.get("turn_stats", {})
        turns = sorted(int(turn) for turn in turn_stats)

        if not turns:
            return html.Div("統計データがありません", style={"padding": "20px"})

        def get_stats(turn):
            return turn_stats.get(turn) or turn_stats.get(str(turn), {})

        x_box, y_box = [], []
        for turn in turns:
            for score in get_stats(turn).get("scores", []):
                x_box.append(turn)
                y_box.append(score)

        fig_score = go.Figure(
            go.Box(x=x_box, y=y_box, name="Score", marker_color=DARK_THEME["accent"])
        )
        fig_score.update_layout(
            title="ターンごとのスコア分布",
            template="plotly_dark",
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor=DARK_THEME["panel"],
            plot_bgcolor=DARK_THEME["background"],
        )

        parent_counts = [get_stats(turn).get("unique_parents", 0) for turn in turns]
        fig_div = go.Figure(
            go.Bar(x=turns, y=parent_counts, marker_color=DARK_THEME["bookmark"])
        )
        fig_div.update_layout(
            title="生存ノードの親の数",
            template="plotly_dark",
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor=DARK_THEME["panel"],
            plot_bgcolor=DARK_THEME["background"],
        )

        valid_counts, pruned_counts, invalid_counts = [], [], []
        for turn in turns:
            stats = get_stats(turn)
            valid_counts.append(
                max(
                    0,
                    stats.get("generated", 0)
                    - stats.get("pruned", 0)
                    - stats.get("invalid", 0),
                )
            )
            pruned_counts.append(stats.get("pruned", 0))
            invalid_counts.append(stats.get("invalid", 0))

        fig_status = go.Figure(
            data=[
                go.Bar(
                    name="有効",
                    x=turns,
                    y=valid_counts,
                    marker_color=DARK_THEME["accent"],
                ),
                go.Bar(
                    name="破棄",
                    x=turns,
                    y=pruned_counts,
                    marker_color=DARK_THEME["pruned"],
                ),
                go.Bar(
                    name="無効",
                    x=turns,
                    y=invalid_counts,
                    marker_color=DARK_THEME["invalid"],
                ),
            ]
        )
        fig_status.update_layout(
            title="ノード生成内訳",
            barmode="stack",
            template="plotly_dark",
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor=DARK_THEME["panel"],
            plot_bgcolor=DARK_THEME["background"],
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
            ),
        )

        common_depths = [
            get_stats(turn).get("common_ancestor_depth", 0) for turn in turns
        ]
        fig_common = go.Figure(
            go.Scatter(
                x=turns,
                y=common_depths,
                mode="lines+markers",
                line=dict(color="#00bcd4"),
            )
        )
        fig_common.update_layout(
            title="有効ノードの共通祖先の深さ",
            template="plotly_dark",
            margin=dict(l=20, r=20, t=40, b=20),
            paper_bgcolor=DARK_THEME["panel"],
            plot_bgcolor=DARK_THEME["background"],
        )
        graph_style = {"marginTop": "10px", "height": "calc(100vh - 240px)"}
        content = [
            dcc.Tabs(
                id="stats-sub-tabs",
                value="tab-score-dist",
                children=[
                    dcc.Tab(
                        label="スコア分布",
                        value="tab-score-dist",
                        style=tab_style,
                        selected_style=tab_selected_style,
                        children=[dcc.Graph(figure=fig_score, style=graph_style)],
                    ),
                    dcc.Tab(
                        label="多様性",
                        value="tab-diversity",
                        style=tab_style,
                        selected_style=tab_selected_style,
                        children=[dcc.Graph(figure=fig_div, style=graph_style)],
                    ),
                    dcc.Tab(
                        label="ノード生成内訳",
                        value="tab-node-status",
                        style=tab_style,
                        selected_style=tab_selected_style,
                        children=[dcc.Graph(figure=fig_status, style=graph_style)],
                    ),
                    dcc.Tab(
                        label="共通祖先深さ",
                        value="tab-common-ancestor",
                        style=tab_style,
                        selected_style=tab_selected_style,
                        children=[dcc.Graph(figure=fig_common, style=graph_style)],
                    ),
                ],
                style={"height": "44px"},
            ),
        ]
        store.turn_stats_content = content
        return content

    @app.callback(
        Output("all-paths-graph", "figure"),
        Input("full-data-store", "data"),
        Input("turn-range-slider", "value"),
        Input("left-tabs", "value"),
    )
    def update_all_graph(_store_signal, turn_range, left_tab):
        # 全体スコア推移タブを開いている時だけ図を作る
        if left_tab != "tab-all-graph":
            return dash.no_update
        processed = store.processed
        nodes = processed.get("current_data", {}).get("nodes", [])
        if not nodes:
            return go.Figure()

        infinite_score = processed.get("current_data", {}).get("INF", 1e18)
        min_turn, max_turn = turn_range
        cached_figure = store.all_graph_cache.get((min_turn, max_turn))
        if cached_figure is not None:
            return cached_figure
        nodes_by_id = processed.get("nodes_dict", {})

        turn_min_all = processed.get("turn_min_all", {})
        start_base_score = turn_min_all.get(min_turn, nodes[0]["score"])

        x, y = [], []
        nodes_by_turn = processed.get("nodes_by_turn", {})
        node_turns = processed.get("node_turns", ())
        first_turn_index = bisect_left(node_turns, min_turn)
        last_turn_index = bisect_right(node_turns, max_turn)
        for turn in node_turns[first_turn_index:last_turn_index]:
            for node in nodes_by_turn[turn]:
                if node["score"] >= infinite_score:
                    continue

                parent_id = node["spid"]
                if parent_id != "-1" and parent_id in nodes_by_id:
                    x += [nodes_by_id[parent_id]["turn"], node["turn"], None]
                    y += [nodes_by_id[parent_id]["score"], node["score"], None]
                elif parent_id == "-1":
                    x += [0, node["turn"], None]
                    y += [start_base_score, node["score"], None]

        fig = go.Figure(
            data=go.Scattergl(
                x=x,
                y=y,
                mode="lines+markers",
                line=dict(color="rgba(150,150,150,0.6)", width=2),
                marker=dict(size=3, color="rgba(200,200,200,0.8)"),
            )
        )
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Turn",
            yaxis_title="Score",
        )
        store.all_graph_cache[(min_turn, max_turn)] = fig
        return fig

    @app.callback(
        Output("clicked-child-store", "data"),
        Input({"type": "child-node-btn", "index": ALL}, "n_clicks"),
        Input("cytoscape-tree", "tapNodeData"),
        prevent_initial_call=True,
    )
    def handle_child_click(n_clicks_list, tap_data):
        ctx = dash.callback_context
        if not ctx.triggered:
            return dash.no_update
        trigger_id_str = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger_id_str == "cytoscape-tree":
            return None

        try:
            trigger_id = json.loads(trigger_id_str)
            return trigger_id["index"]
        except Exception:
            return dash.no_update

    @app.callback(
        [
            Output("node-detail-output", "children"),
            Output("action-path-output", "value"),
            Output("node-state-output", "children"),
            Output("score-history-graph", "figure"),
            Output("cytoscape-tree", "stylesheet"),
        ],
        [
            Input("cytoscape-tree", "tapNodeData"),
            Input("show-goal-path-store", "data"),
            Input("clicked-child-store", "data"),
            Input("info-tabs", "value"),
        ],
        [State("full-data-store", "data")],
    )
    def display_node(node_data, show_goal, clicked_child, info_tab, store_signal):
        # 盤面とスコア図は該当タブを開いている時だけ作る
        # info-tabs の切替だけなら詳細、操作列、スタイルシートは更新しない
        only_tab_switch = bool(
            callback_context.triggered
        ) and callback_context.triggered[0]["prop_id"].startswith("info-tabs")
        want_board = info_tab == "tab-state"
        want_score = info_tab == "tab-score"
        processed = store.processed
        if not processed:
            return (
                html.Div(
                    "ノードを選択してください",
                    style={"color": "#aaa", "padding": "10px"},
                ),
                "",
                "",
                go.Figure(),
                BASE_STYLESHEET,
            )

        inf_value = processed.get("current_data", {}).get("INF", 1e18)
        nodes_dict = processed.get("nodes_dict", {})
        children_dict = processed.get("children_dict", {})
        snapshots_dict = processed.get("snapshots_dict", {})
        max_turn = processed.get("max_t", 10)

        y_range = processed.get("y_range")

        detail_elements = html.Div(
            "ノードを選択してください", style={"color": "#aaa", "padding": "10px"}
        )
        action_seq = ""
        state_visual = html.Div(
            "ノードを選択してください", style={"color": "#aaa", "padding": "10px"}
        )
        fig = go.Figure()
        new_styles = list(BASE_STYLESHEET)

        new_styles.append(
            {
                "selector": ".out-of-range",
                "style": {"opacity": 0.4},
            }
        )

        if node_data:
            if node_data["id"] == "-1":
                target = {
                    "node_id": "-1",
                    "score": "N/A",
                    "turn": 0,
                    "action": "Root",
                    "status": "Start",
                }
            else:
                target = nodes_dict.get(node_data["id"])

            if target:
                detail_text = (
                    f"ID: {target['node_id']}\n"
                    f"Score: {target['score']}\n"
                    f"Turn: {target['turn']}\n"
                    f"Action: {target.get('action','')}\n"
                    f"Hash: {target.get('hash','N/A')}\n"
                    f"Status: {target.get('status','')}"
                )

                children_ids = children_dict.get(str(target["node_id"]), [])

                child_btns_container = None
                if children_ids:
                    btn_list = []
                    for cid in children_ids:
                        is_active = str(cid) == str(clicked_child)
                        bg_color = "#ffeb3b" if is_active else DARK_THEME["accent"]
                        color = "#000" if is_active else "#fff"
                        btn_list.append(
                            html.Button(
                                f"ID: {cid}",
                                id={"type": "child-node-btn", "index": str(cid)},
                                className="modern-btn",
                                style={
                                    "backgroundColor": bg_color,
                                    "color": color,
                                    "fontSize": "11px",
                                    "padding": "4px 8px",
                                },
                            )
                        )
                    child_btns_container = html.Div(
                        style={
                            "marginTop": "10px",
                            "backgroundColor": "#1e1e1e",
                            "padding": "10px",
                            "border": f'1px solid {DARK_THEME["border"]}',
                        },
                        children=[
                            html.Span(
                                "子ノード:",
                                style={
                                    "fontWeight": "bold",
                                    "fontSize": "12px",
                                    "display": "block",
                                    "marginBottom": "5px",
                                },
                            ),
                            html.Div(
                                btn_list,
                                style={
                                    "display": "flex",
                                    "flexWrap": "wrap",
                                    "gap": "5px",
                                },
                            ),
                        ],
                    )

                detail_elements = html.Div(
                    [
                        html.Pre(
                            detail_text,
                            style={
                                "whiteSpace": "pre-wrap",
                                "backgroundColor": "#1e1e1e",
                                "padding": "10px",
                                "margin": "0",
                                "border": f'1px solid {DARK_THEME["border"]}',
                            },
                        ),
                        child_btns_container if child_btns_container else html.Div(),
                    ]
                )

                target_id = str(target["node_id"])
                path_data = store.node_path(target_id)
                path_ids = list(path_data.node_ids)
                action_seq = path_data.action_sequence
                if want_board:
                    state_visual = store.board_cache.get(action_seq)
                    if state_visual is None:
                        state_visual = store.generate_board_visual(action_seq)
                        store.board_cache[action_seq] = state_visual

                subtree_data = None if only_tab_switch else store.subtree(target_id)

                if want_score:
                    path_scores = [
                        nodes_dict[node_id]["score"]
                        for node_id in path_ids
                        if node_id in nodes_dict
                    ]
                    path_turns = [
                        nodes_dict[node_id]["turn"]
                        for node_id in path_ids
                        if node_id in nodes_dict
                    ]
                    path_thresholds = [
                        snapshots_dict[t]["threshold"] if t in snapshots_dict else None
                        for t in path_turns
                    ]

                    if path_turns:
                        fig.add_trace(
                            go.Scatter(
                                x=path_turns[::-1],
                                y=path_scores[::-1],
                                mode="lines+markers",
                                name="ノードスコア",
                                line=dict(color="#4fc3f7"),
                            )
                        )

                    val_th_x = [
                        t
                        for t, th in zip(path_turns[::-1], path_thresholds[::-1])
                        if th is not None
                        and isinstance(th, (int, float))
                        and th < inf_value
                    ]
                    val_th_y = [
                        th
                        for th in path_thresholds[::-1]
                        if th is not None
                        and isinstance(th, (int, float))
                        and th < inf_value
                    ]
                    if val_th_x:
                        fig.add_trace(
                            go.Scatter(
                                x=val_th_x,
                                y=val_th_y,
                                mode="lines",
                                name="閾値",
                                line=dict(color="#ff5252", dash="dash"),
                            )
                        )

                    fig.update_layout(
                        template="plotly_dark",
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                        margin=dict(l=20, r=20, t=20, b=20),
                        height=300,
                        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
                        yaxis=dict(range=y_range) if y_range else None,
                        xaxis=dict(range=[0, max_turn], title="Turn"),
                    )

                if subtree_data is not None and subtree_data.node_ids:
                    new_styles.append(
                        {
                            "selector": subtree_data.node_selector,
                            "style": {"border-width": "3px", "border-color": "#ff9800"},
                        }
                    )
                if subtree_data is not None and subtree_data.edge_ids:
                    new_styles.append(
                        {
                            "selector": subtree_data.edge_selector,
                            "style": {
                                "width": 3,
                                "line-color": "#ff9800",
                                "target-arrow-color": "#ff9800",
                            },
                        }
                    )
                if not only_tab_switch and path_ids:
                    new_styles.append(
                        {
                            "selector": path_data.node_selector,
                            "style": {
                                "border-width": "3px",
                                "border-color": DARK_THEME["highlight"],
                            },
                        }
                    )

                if not only_tab_switch and path_data.edge_selector:
                    new_styles.append(
                        {
                            "selector": path_data.edge_selector,
                            "style": {
                                "width": 4,
                                "line-color": DARK_THEME["highlight"],
                                "target-arrow-color": DARK_THEME["highlight"],
                            },
                        }
                    )

                if not only_tab_switch and clicked_child:
                    new_styles.append(
                        {
                            "selector": f'node[id="{clicked_child}"]',
                            "style": {
                                "border-width": "5px",
                                "border-color": "#ffeb3b",
                                "background-color": "#ffeb3b",
                                "color": "#000",
                                "font-size": "14px",
                                "font-weight": "bold",
                                "width": "45px",
                                "height": "45px",
                                "z-index": "100",
                            },
                        }
                    )

        if show_goal and not only_tab_switch:
            goal_path_ids = processed.get("goal_path_ids", set())
            goal_edge_ids = processed.get("goal_edge_ids", set())

            if goal_path_ids:
                new_styles.append(
                    {
                        "selector": processed.get("goal_node_selector", ""),
                        "style": {"border-width": "5px", "border-color": "#00e5ff"},
                    }
                )
            if goal_edge_ids:
                new_styles.append(
                    {
                        "selector": processed.get("goal_edge_selector", ""),
                        "style": {
                            "width": 6,
                            "line-color": "#00e5ff",
                            "target-arrow-color": "#00e5ff",
                            "z-index": "100",
                        },
                    }
                )

        board_out = state_visual if want_board else dash.no_update
        score_out = fig if want_score else dash.no_update
        if only_tab_switch:
            return dash.no_update, dash.no_update, board_out, score_out, dash.no_update
        return detail_elements, action_seq, board_out, score_out, new_styles

    @app.callback(
        Output("collapsed-nodes-store", "data"),
        Input("toggle-fold-button", "n_clicks"),
        Input("fold-all-pruned-button", "n_clicks"),
        State("cytoscape-tree", "tapNodeData"),
        State("collapsed-nodes-store", "data"),
        prevent_initial_call=True,
    )
    def manage_folding(n_fold, n_fold_all, tap_data, collapsed):
        trigger = callback_context.triggered[0]["prop_id"]
        if "fold-all-pruned-button" in trigger:
            pruned_ids = store.processed.get("pruned_ids", ())
            pruned_set = set(pruned_ids)
            active_collapsed = [c for c in collapsed if c in pruned_set]
            if active_collapsed:
                collapsed = [c for c in collapsed if c not in pruned_set]
            else:
                collapsed_set = set(collapsed)
                collapsed.extend(
                    [node_id for node_id in pruned_ids if node_id not in collapsed_set]
                )
        elif (
            "toggle-fold-button" in trigger and tap_data and tap_data.get("id") != "-1"
        ):
            node_id = tap_data["id"]
            if node_id in collapsed:
                collapsed.remove(node_id)
            else:
                collapsed.append(node_id)
        return collapsed

    @app.callback(
        Output("bookmark-nodes-store", "data"),
        Output("bookmark-list-output", "children"),
        Output("toggle-bookmark-button", "children"),
        Input("toggle-bookmark-button", "n_clicks"),
        State("cytoscape-tree", "tapNodeData"),
        State("bookmark-nodes-store", "data"),
        prevent_initial_call=True,
    )
    def manage_bookmarks(n_clicks, tap_data, bookmarks):
        btn_label = "⭐ ブックマークに追加"
        if tap_data and tap_data.get("id") != "-1":
            node_id = tap_data["id"]
            if node_id in bookmarks:
                bookmarks.remove(node_id)
            else:
                bookmarks.append(node_id)
                btn_label = "⭐ ブックマークを解除"

        processed = store.processed
        nodes_dict = processed.get("nodes_dict", {})

        elements = []
        for bookmarked_id in bookmarks:
            node = nodes_dict.get(bookmarked_id)
            if node:
                elements.append(
                    html.Div(
                        style={
                            "border": "1px solid #444",
                            "padding": "10px",
                            "marginBottom": "10px",
                            "backgroundColor": "#2d2d30",
                        },
                        children=[
                            html.B(
                                f"Node ID: {bookmarked_id}",
                                style={"color": DARK_THEME["bookmark"]},
                            ),
                            html.P(
                                f"Turn: {node['turn']} | Score: {node['score']}",
                                style={"margin": "5px 0"},
                            ),
                            html.P(
                                f"Action: {node.get('action', '')} | Hash: {node.get('hash', 'N/A')}",
                                style={"margin": "0", "fontSize": "11px"},
                            ),
                        ],
                    )
                )

        return (
            bookmarks,
            (
                elements
                if elements
                else html.Div("ブックマークはありません", style={"color": "#aaa"})
            ),
            btn_label,
        )

    @app.callback(
        Output("hover-action-output", "children"),
        Input("cytoscape-tree", "mouseoverEdgeData"),
    )
    def display_hover_edge(edge_data):
        return (
            f"Action: {edge_data['action']}"
            if edge_data and "action" in edge_data
            else ""
        )

    @app.callback(
        Output("right-panel-container", "className"),
        Output("right-panel-toggle-btn", "style"),
        Output("pin-toggle-btn", "children"),
        Output("right-panel-toggle-btn", "children"),
        Input("pin-toggle-btn", "n_clicks"),
        Input("right-panel-toggle-btn", "n_clicks"),
        State("right-panel-container", "className"),
        prevent_initial_call=True,
    )
    def toggle_right_panel(pin_clicks, toggle_clicks, current_class):
        trigger = callback_context.triggered[0]["prop_id"]
        is_pinned = "right-panel-pinned" in current_class
        is_open = "open" in current_class

        if "pin-toggle-btn" in trigger:
            is_pinned, is_open = not is_pinned, False
        elif "right-panel-toggle-btn" in trigger:
            is_open = not is_open

        if is_pinned:
            return (
                "right-panel right-panel-pinned",
                {"display": "none"},
                "📌 ピン留め解除",
                "◀",
            )
        return (
            f"right-panel right-panel-unpinned{' open' if is_open else ''}",
            {"display": "flex"},
            "📌 ピン留めする",
            "▶" if is_open else "◀",
        )

    @app.callback(
        Output("auto-play-interval", "interval"),
        Input("playback-speed-slider", "value"),
    )
    def update_playback_speed(speed_level):
        max_interval = 1500
        min_interval = 50
        progress = (speed_level - 1) / 9.0
        return max_interval - int((max_interval - min_interval) * progress)

    @app.callback(
        Output("show-goal-path-store", "data"),
        Output("highlight-goal-button", "children"),
        Input("highlight-goal-button", "n_clicks"),
        State("show-goal-path-store", "data"),
        prevent_initial_call=True,
    )
    def toggle_goal_path(n_clicks, is_active):
        new_state = not is_active
        label = "🏁 ゴール経路を解除" if new_state else "🏁 ゴール経路を強調"
        return new_state, label

    return app
