import json
import os
import time

import dash
import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback_context, dcc, html

from beam_config import (
    BASE_STYLESHEET,
    DARK_THEME,
    generate_assets,
    tab_selected_style,
    tab_style,
)
from beam_data import compute_compact_layout, load_and_process_data
from visualizer import generate_board_visual

cyto.load_extra_layouts()
generate_assets()

_DATA_CACHE = {"processed": {}, "compact_layout_cache": {}}

app = dash.Dash(__name__, update_title=None, suppress_callback_exceptions=True)

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
                            style={"marginRight": "10px", "backgroundColor": "#4caf50"},
                        ),
                        html.Button(
                            "再生", id="play-button", n_clicks=0, className="modern-btn"
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
                            placeholder="スコア/Action/Hash検索...",
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
                                {"label": " スコアヒートマップ", "value": "heatmap"},
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
                            style={"padding": "10px", "flex": "1", "overflowY": "auto"},
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
                                                            style={"marginTop": "15px"},
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
                                                    config={"displayModeBar": False},
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
def load_data(_n_clicks, _keyboard_data):
    global _DATA_CACHE
    processed, max_turn, _marks = load_and_process_data("history.json")
    _DATA_CACHE["processed"] = processed
    _DATA_CACHE["compact_layout_cache"] = {}
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
def handle_play(n_clicks, _n_intervals, current_range, max_turn):
    trigger = callback_context.triggered[0]["prop_id"]
    if "play-button" in trigger:
        is_disabled = n_clicks % 2 == 0
        return current_range, "再生" if is_disabled else "停止", is_disabled
    if "auto-play-interval" in trigger:
        new_max = current_range[1] + 1
        if new_max > max_turn:
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
    _store_signal,
    turn_range,
    visibility,
    collapsed_ids,
    bookmarked_ids,
    _n_search,
    left_tab,
    tree_direction,
    _n_fit,
    search_query,
    current_elements,
):
    if left_tab != "tab-tree":
        return dash.no_update, dash.no_update

    trigger_id = (
        callback_context.triggered[0]["prop_id"] if callback_context.triggered else ""
    )
    should_fit = trigger_id in ["fit-button.n_clicks", "full-data-store.data", ""]

    layout_config = {
        "name": "preset",
        "animate": False,
        "fit": should_fit,
        "padding": 30,
        "refresh": time.time(),
    }

    if trigger_id == "fit-button.n_clicks" and current_elements:
        return current_elements, layout_config

    processed = _DATA_CACHE.get("processed", {})
    nodes = processed.get("current_data", {}).get("nodes", [])
    if not nodes:
        return [], dash.no_update

    nodes_by_id = processed.get("nodes_dict", {})
    children_by_parent = processed.get("children_dict", {})
    snapshots_by_turn = processed.get("snapshots_dict", {})
    turn_stats = processed.get("turn_stats", {})
    base_positions = processed.get("base_positions", {})
    inf_value = processed.get("current_data", {}).get("INF", 1e18)

    min_turn, max_turn = turn_range
    active_path = set()

    active_turn = max_turn
    while active_turn >= min_turn:
        active_nodes = snapshots_by_turn.get(active_turn, {}).get("active", [])
        if active_nodes:
            terminal_ids = set(str(node_id) for node_id in active_nodes)
            break
        active_turn -= 1
    else:
        terminal_ids = set()

    current_ids = list(terminal_ids)
    while current_ids:
        next_nodes = []
        for node_id in current_ids:
            if node_id in nodes_by_id:
                active_path.add(node_id)
                parent_id = str(nodes_by_id[node_id]["parent_id"])
                if parent_id != "-1" and parent_id not in active_path:
                    next_nodes.append(parent_id)
        current_ids = next_nodes
    active_path.add("-1")

    compact_mode = "compact" in visibility
    positions = base_positions
    if compact_mode and active_path:
        cache = _DATA_CACHE.setdefault("compact_layout_cache", {})
        cache_key = active_turn
        compact_positions = cache.get(cache_key)
        if compact_positions is None:
            raw_positions = compute_compact_layout(
                active_path, children_by_parent, nodes_by_id, root_id="-1"
            )
            compact_positions = {}
            for node_id, x in raw_positions.items():
                if node_id == "-1":
                    depth = 0
                elif node_id in nodes_by_id:
                    depth = nodes_by_id[node_id]["turn"]
                else:
                    depth = 0
                compact_positions[node_id] = {
                    "depth": depth,
                    "breadth_center": x,
                }
            cache[cache_key] = compact_positions
        positions = compact_positions

    collapsed_set = set(collapsed_ids)
    is_ancestor_collapsed = {"-1": False}
    for node in sorted(nodes, key=lambda item: item.get("turn", 0)):
        node_id = str(node["node_id"])
        parent_id = str(node["parent_id"])
        is_ancestor_collapsed[node_id] = (
            parent_id in collapsed_set
        ) or is_ancestor_collapsed.get(parent_id, False)

    show_pruned = "show_pruned" in visibility and not compact_mode
    use_heatmap = "heatmap" in visibility

    def get_heatmap_color(score, turn):
        if score >= inf_value:
            return DARK_THEME["inf"]
        stats = turn_stats.get(turn)
        if not stats:
            return "rgb(128, 128, 128)"
        min_score, max_score = stats["min"], stats["max"]
        ratio = (
            0.5
            if max_score == min_score
            else (score - min_score) / (max_score - min_score)
        )
        r, g, b = int(25 + ratio * 186), int(118 - ratio * 71), int(210 - ratio * 163)
        return f"rgb({r}, {g}, {b})"

    if tree_direction == "TB":
        depth_gap = 200
        breadth_gap = 100
    else:
        depth_gap = 300
        breadth_gap = 60

    start_position = positions.get("-1", {"depth": 0, "breadth_center": 0.0})
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
    for node in nodes:
        node_id = str(node["node_id"])
        if is_ancestor_collapsed.get(node_id, False):
            continue
        if min_turn <= node["turn"] <= max_turn:
            if not show_pruned and node_id not in active_path:
                continue
            visible_ids.add(node_id)
            parent_id = str(node["parent_id"])
            while parent_id != "-1" and parent_id not in visible_ids:
                if (
                    parent_id in nodes_by_id
                    and nodes_by_id[parent_id]["turn"] < min_turn
                ):
                    visible_ids.add(parent_id)
                    parent_id = str(nodes_by_id[parent_id]["parent_id"])
                else:
                    break

    visible_nodes = [
        nodes_by_id[node_id] for node_id in visible_ids if node_id in nodes_by_id
    ]
    visible_nodes.sort(
        key=lambda node: (node["turn"], node["parent_id"], node["score"])
    )

    valid_ids = {"-1"}
    for node in visible_nodes:
        node_id = str(node["node_id"])
        valid_ids.add(node_id)

        if node.get("is_answer", False):
            classes = "status-answer"
        elif node["status"] == 2:
            classes = "status-invalid"
        elif node_id in active_path:
            classes = "status-active"
        else:
            classes = "status-pruned"

        if node_id in collapsed_ids:
            classes += " folded"
        if node_id in bookmarked_ids:
            classes += " bookmarked"

        if search_query and (
            search_query in str(node["score"])
            or search_query in node.get("action", "")
            or search_query in str(node.get("hash", ""))
        ):
            classes += " searched"

        if node["turn"] < min_turn:
            classes += " out-of-range"

        element = {
            "data": {
                "id": node_id,
                "label": f"T:{node['turn']}\nS:{node['score']}",
            },
            "classes": classes,
        }

        position = positions.get(node_id, {"depth": 0, "breadth_center": 0.0})
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
            element["data"]["bg_color"] = get_heatmap_color(node["score"], node["turn"])
            element["classes"] += " heatmap-node"

        elements.append(element)

    for node in visible_nodes:
        node_id = str(node["node_id"])
        parent_id = str(node["parent_id"])
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
        "fit": should_fit,
        "padding": 30,
        "refresh": time.time(),
    }

    return elements, layout_config


@app.callback(
    Output("turn-stats-container", "children"), Input("full-data-store", "data")
)
def update_turn_stats(_store_signal):
    processed = _DATA_CACHE.get("processed")
    if not processed:
        return html.Div("データがありません", style={"padding": "20px"})

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
                name="有効", x=turns, y=valid_counts, marker_color=DARK_THEME["accent"]
            ),
            go.Bar(
                name="破棄", x=turns, y=pruned_counts, marker_color=DARK_THEME["pruned"]
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
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    common_depths = [get_stats(turn).get("common_ancestor_depth", 0) for turn in turns]
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
    return [
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


@app.callback(
    Output("all-paths-graph", "figure"),
    [Input("full-data-store", "data"), Input("turn-range-slider", "value")],
)
def update_all_graph(_store_signal, turn_range):
    processed = _DATA_CACHE.get("processed", {})
    nodes = processed.get("current_data", {}).get("nodes", [])
    if not nodes:
        return go.Figure()

    infinite_score = processed.get("current_data", {}).get("INF", 1e18)
    min_turn, max_turn = turn_range
    nodes_by_id = processed.get("nodes_dict", {})

    start_base_score = min(
        [node["score"] for node in nodes if node["turn"] == min_turn]
        or [nodes[0]["score"]]
    )

    x, y = [], []
    for node in nodes:
        if not min_turn <= node["turn"] <= max_turn or node["score"] >= infinite_score:
            continue

        parent_id = str(node["parent_id"])
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
    except:
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
    ],
    [State("full-data-store", "data")],
)
def display_node(node_data, show_goal, clicked_child, store_signal):
    processed = _DATA_CACHE.get("processed", {})
    if not processed:
        return (
            html.Div(
                "ノードを選択してください", style={"color": "#aaa", "padding": "10px"}
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
    valid_scores = processed.get("valid_scores", [])
    turn_stats = processed.get("turn_stats", {})
    max_turn = max([int(t) for t in turn_stats.keys()]) if turn_stats else 10

    y_range = (
        [
            min(valid_scores) - (max(valid_scores) - min(valid_scores)) * 0.05,
            max(valid_scores) + (max(valid_scores) - min(valid_scores)) * 0.05,
        ]
        if valid_scores
        else None
    )

    detail_elements = html.Div(
        "ノードを選択してください", style={"color": "#aaa", "padding": "10px"}
    )
    action_seq = ""
    state_visual = html.Div(
        "ノードを選択してください", style={"color": "#aaa", "padding": "10px"}
    )
    fig = go.Figure()
    new_styles = list(BASE_STYLESHEET)

    new_styles.append({"selector": ".out-of-range", "style": {"opacity": 0.4}})

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
            state_json = json.dumps(
                target.get("state_info", {}), indent=2, ensure_ascii=False
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
                            style={"display": "flex", "flexWrap": "wrap", "gap": "5px"},
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

            path_ids = []
            node_id = str(target["node_id"])
            while node_id != "-1" and node_id in nodes_dict:
                path_ids.append(node_id)
                node_id = str(nodes_dict.get(node_id, {}).get("parent_id", "-1"))
            path_ids.append("-1")

            action_seq = "".join(
                [
                    nodes_dict[node_id].get("action", "")
                    for node_id in path_ids[::-1]
                    if node_id in nodes_dict
                ]
            )
            state_visual = generate_board_visual(action_seq)

            subtree_node_ids, subtree_edge_ids, queue, target_id_str = (
                [],
                [],
                [str(target["node_id"])],
                str(target["node_id"]),
            )
            while queue:
                curr_node = queue.pop()
                if curr_node != target_id_str:
                    subtree_node_ids.append(curr_node)
                if curr_node in children_dict:
                    for child in children_dict[curr_node]:
                        subtree_edge_ids.append(f"e{curr_node}_{child}")
                        queue.append(child)

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
                if th is not None and isinstance(th, (int, float)) and th < inf_value
            ]
            val_th_y = [
                th
                for th in path_thresholds[::-1]
                if th is not None and isinstance(th, (int, float)) and th < inf_value
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

            if subtree_node_ids:
                new_styles.append(
                    {
                        "selector": ",".join(
                            [f'node[id="{node_id}"]' for node_id in subtree_node_ids]
                        ),
                        "style": {"border-width": "3px", "border-color": "#ff9800"},
                    }
                )
            if subtree_edge_ids:
                new_styles.append(
                    {
                        "selector": ",".join(
                            [f'edge[id="{edge_id}"]' for edge_id in subtree_edge_ids]
                        ),
                        "style": {
                            "width": 3,
                            "line-color": "#ff9800",
                            "target-arrow-color": "#ff9800",
                        },
                    }
                )
            if path_ids:
                new_styles.append(
                    {
                        "selector": ",".join(
                            [f'node[id="{node_id}"]' for node_id in path_ids]
                        ),
                        "style": {
                            "border-width": "3px",
                            "border-color": DARK_THEME["highlight"],
                        },
                    }
                )

            path_edges_ids = [
                f"e{path_ids[i+1]}_{path_ids[i]}" for i in range(len(path_ids) - 1)
            ]
            if path_edges_ids:
                new_styles.append(
                    {
                        "selector": ",".join(
                            [f'edge[id="{edge_id}"]' for edge_id in path_edges_ids]
                        ),
                        "style": {
                            "width": 4,
                            "line-color": DARK_THEME["highlight"],
                            "target-arrow-color": DARK_THEME["highlight"],
                        },
                    }
                )

            if clicked_child:
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

    if show_goal:
        goal_nodes = [
            node for node in nodes_dict.values() if node.get("is_answer", False)
        ]
        goal_path_ids = set()
        goal_edge_ids = set()

        for goal_node in goal_nodes:
            node_id = str(goal_node["node_id"])
            while node_id != "-1" and node_id in nodes_dict:
                goal_path_ids.add(node_id)
                parent_id = str(nodes_dict[node_id]["parent_id"])
                if parent_id != "-1" or node_id != "-1":
                    goal_edge_ids.add(f"e{parent_id}_{node_id}")
                node_id = parent_id
            goal_path_ids.add("-1")

        if goal_path_ids:
            new_styles.append(
                {
                    "selector": ",".join(
                        [f'node[id="{node_id}"]' for node_id in goal_path_ids]
                    ),
                    "style": {
                        "border-width": "5px",
                        "border-color": "#00e5ff",
                    },
                }
            )
        if goal_edge_ids:
            new_styles.append(
                {
                    "selector": ",".join(
                        [f'edge[id="{edge_id}"]' for edge_id in goal_edge_ids]
                    ),
                    "style": {
                        "width": 6,
                        "line-color": "#00e5ff",
                        "target-arrow-color": "#00e5ff",
                        "z-index": "100",
                    },
                }
            )

    return detail_elements, action_seq, state_visual, fig, new_styles


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
        nodes = (
            _DATA_CACHE.get("processed", {}).get("current_data", {}).get("nodes", [])
        )
        pruned_ids = [str(n["node_id"]) for n in nodes if n["status"] == 1]
        active_collapsed = [c for c in collapsed if c in pruned_ids]
        if active_collapsed:
            collapsed = [c for c in collapsed if c not in pruned_ids]
        else:
            collapsed.extend(
                [node_id for node_id in pruned_ids if node_id not in collapsed]
            )
    elif "toggle-fold-button" in trigger and tap_data and tap_data.get("id") != "-1":
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

    processed = _DATA_CACHE.get("processed", {})
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
        f"Action: {edge_data['action']}" if edge_data and "action" in edge_data else ""
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
    current_interval = max_interval - int((max_interval - min_interval) * progress)
    return current_interval


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


if __name__ == "__main__":
    app.run(debug=True)
