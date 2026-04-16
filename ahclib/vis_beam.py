import json
import os
import dash
from dash import html, dcc, Input, Output, State, ALL, callback_context
import dash_cytoscape as cyto

cyto.load_extra_layouts()
import plotly.graph_objects as go
import time

app = dash.Dash(__name__, update_title=None)

DARK_THEME = {
    "background": "#1e1e1e",
    "panel": "#252526",
    "text": "#d4d4d4",
    "border": "#333",
    "accent": "#1976d2",
    "pruned": "#555555",
    "invalid": "#d32f2f",
    "highlight": "#ffeb3b",
    "inf": "#8e24aa",
}

BASE_STYLESHEET = [
    {
        "selector": "node",
        "style": {
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "10px",
            "width": "60px",
            "height": "30px",
            "shape": "rectangle",
            "color": "#ffffff",
            "text-wrap": "wrap",
            "border-width": "0px",
        },
    },
    {"selector": ".status-active", "style": {"background-color": DARK_THEME["accent"]}},
    {
        "selector": ".status-pruned",
        "style": {
            "background-color": DARK_THEME["pruned"],
            "width": "10px",
            "height": "10px",
            "font-size": "0px",
        },
    },
    {
        "selector": ".status-invalid",
        "style": {
            "background-color": DARK_THEME["invalid"],
            "width": "8px",
            "height": "8px",
            "font-size": "0px",
        },
    },
    {
        "selector": ".folded",
        "style": {
            "border-width": "3px",
            "border-color": "#ffffff",
            "border-style": "double",
        },
    },
    {
        "selector": ".searched",
        "style": {"border-width": "4px", "border-color": "#00ff00"},
    },
    {
        "selector": ".heatmap-node",
        "style": {
            "background-color": "data(bg_color)",
            "color": "#ffffff",
            "text-outline-width": "1px",
            "text-outline-color": "#000000",
        },
    },
    {
        "selector": "edge",
        "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "width": 2,
            "line-color": "#666666",
            "target-arrow-color": "#666666",
            "events": "no",
        },
    },
    {
        "selector": ".dummy-edge",
        "style": {
            "line-style": "dashed",
            "line-color": "#444444",
            "target-arrow-color": "#444444",
        },
    },
]

tab_style = {
    "backgroundColor": "#2d2d30",
    "color": "#d4d4d4",
    "border": f'1px solid {DARK_THEME["border"]}',
    "padding": "10px",
    "cursor": "pointer",
}

tab_selected_style = {
    "backgroundColor": DARK_THEME["accent"],
    "color": "#ffffff",
    "border": f'1px solid {DARK_THEME["accent"]}',
    "padding": "10px",
    "cursor": "pointer",
}

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
        dcc.Store(id="comparison-nodes-store", data=[]),
        dcc.Interval(id="auto-play-interval", interval=1000, disabled=True),
        html.Div(
            style={
                "padding": "10px",
                "borderBottom": f'1px solid {DARK_THEME["border"]}',
                "backgroundColor": DARK_THEME["panel"],
                "display": "flex",
                "gap": "20px",
                "flexWrap": "wrap",
                "alignItems": "center",
            },
            children=[
                html.Div(
                    style={"flex": "1", "minWidth": "300px"},
                    children=[
                        html.Label("表示ターン区間:", style={"fontWeight": "bold"}),
                        dcc.RangeSlider(
                            id="turn-range-slider",
                            min=0,
                            max=1,
                            step=1,
                            value=[0, 1],
                            marks={0: "0"},
                            tooltip={"placement": "bottom", "always_visible": True},
                        ),
                    ],
                ),
                html.Div(
                    children=[
                        html.Button(
                            "再読み込み",
                            id="reload-button",
                            style={"marginRight": "10px"},
                        ),
                        html.Button("再生", id="play-button", n_clicks=0),
                        html.Label(
                            " (←/→キーで1ターン移動)",
                            style={"fontSize": "12px", "marginLeft": "5px"},
                        ),
                    ]
                ),
                html.Div(
                    children=[
                        dcc.Input(
                            id="search-input",
                            placeholder="スコアまたはActionで検索...",
                            style={"padding": "5px"},
                        ),
                        html.Button(
                            "検索", id="search-button", style={"marginLeft": "5px"}
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
                            ],
                            value=["show_pruned"],
                        )
                    ]
                ),
                html.Div(
                    id="hover-action-output",
                    style={
                        "marginLeft": "20px",
                        "fontWeight": "bold",
                        "color": DARK_THEME["highlight"],
                        "minWidth": "200px",
                    },
                ),
            ],
        ),
        html.Div(
            style={"display": "flex", "flex": "1", "overflow": "hidden"},
            children=[
                html.Div(
                    style={
                        "flex": "3",
                        "display": "flex",
                        "flexDirection": "column",
                        "borderRight": f'1px solid {DARK_THEME["border"]}',
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
                                        cyto.Cytoscape(
                                            id="cytoscape-tree",
                                            layout={
                                                "name": "dagre",
                                                "rankDir": "LR",  # 描画方向を Left-to-Right に変更
                                                "nodeSep": 5,  # 同じ階層内のノード間隔を極小化
                                                "rankSep": 40,  # 階層（ターン）間の間隔
                                                "spacingFactor": 1,  # 全体をさらに圧縮
                                            },
                                            style={
                                                "width": "100%",
                                                "height": "calc(100vh - 150px)",
                                            },
                                            stylesheet=BASE_STYLESHEET,
                                            elements=[],
                                            zoom=1.0,
                                            minZoom=0.05,
                                            maxZoom=5.0,
                                            autoungrabify=True,
                                            wheelSensitivity=0.2,
                                        )
                                        # cyto.Cytoscape(
                                        #     id="cytoscape-tree",
                                        #     layout={
                                        #         "name": "dagre",  # breadthfirst から変更
                                        #         "nodeSep": 30,  # ノードの左右の最低間隔
                                        #         "rankSep": 80,  # 階層の上下の最低間隔
                                        #     },
                                        #     style={
                                        #         "width": "100%",
                                        #         "height": "calc(100vh - 150px)",
                                        #     },
                                        #     stylesheet=BASE_STYLESHEET,
                                        #     elements=[],
                                        #     zoom=1.0,
                                        #     minZoom=0.05,
                                        #     maxZoom=5.0,
                                        #     autoungrabify=True,
                                        #     wheelSensitivity=0.2,
                                        # )
                                        # 元
                                        # cyto.Cytoscape(
                                        #     id="cytoscape-tree",
                                        #     layout={
                                        #         "name": "breadthfirst",
                                        #         "roots": "#-1",
                                        #         "directed": True,
                                        #         "spacingFactor": 1.1,
                                        #     },
                                        #     style={
                                        #         "width": "100%",
                                        #         "height": "calc(100vh - 150px)",
                                        #     },
                                        #     stylesheet=BASE_STYLESHEET,
                                        #     elements=[],
                                        #     zoom=1.0,
                                        #     minZoom=0.05,
                                        #     maxZoom=5.0,
                                        #     autoungrabify=True,
                                        #     wheelSensitivity=0.2,
                                        # )
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
                            ],
                        )
                    ],
                ),
                html.Div(
                    style={
                        "flex": "2",
                        "backgroundColor": DARK_THEME["panel"],
                        "padding": "10px",
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
                                                    "この枝を折りたたむ/展開",
                                                    id="toggle-fold-button",
                                                    style={
                                                        "padding": "5px 10px",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                                html.Button(
                                                    "破棄ノード一括折りたたみ/展開",
                                                    id="fold-all-pruned-button",
                                                    style={
                                                        "marginLeft": "10px",
                                                        "padding": "5px 10px",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                                html.Button(
                                                    "比較リストに追加",
                                                    id="add-comparison-button",
                                                    style={
                                                        "marginLeft": "10px",
                                                        "padding": "5px 10px",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                                html.Pre(
                                                    id="node-detail-output",
                                                    style={
                                                        "whiteSpace": "pre-wrap",
                                                        "backgroundColor": "#1e1e1e",
                                                        "padding": "10px",
                                                        "marginTop": "10px",
                                                        "border": f'1px solid {DARK_THEME["border"]}',
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
                                                    style={"position": "relative"},
                                                    children=[
                                                        dcc.Textarea(
                                                            id="action-path-output",
                                                            readOnly=True,
                                                            placeholder="根からこのノードまでの操作列がここに表示されます",
                                                            style={
                                                                "width": "100%",
                                                                "height": "80px",
                                                                "backgroundColor": "#1e1e1e",
                                                                "color": "#d4d4d4",
                                                                "border": f'1px solid {DARK_THEME["border"]}',
                                                                "borderRadius": "4px",
                                                                "fontFamily": "monospace",
                                                                "padding": "8px",
                                                                "paddingRight": "35px",  # アイコンが被らないように右側の余白を確保
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
                                    label="経路比較",
                                    value="tab-compare",
                                    style=tab_style,
                                    selected_style=tab_selected_style,
                                    children=[
                                        html.Button(
                                            "比較リストをクリア",
                                            id="clear-comparison-button",
                                            style={
                                                "marginTop": "10px",
                                                "padding": "5px 10px",
                                                "cursor": "pointer",
                                            },
                                        ),
                                        html.Div(
                                            id="comparison-output",
                                            style={"marginTop": "15px"},
                                        ),
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
                                        html.Pre(
                                            id="node-state-output",
                                            style={
                                                "whiteSpace": "pre-wrap",
                                                "backgroundColor": "#1e1e1e",
                                                "padding": "10px",
                                                "marginTop": "10px",
                                                "border": f'1px solid {DARK_THEME["border"]}',
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
    path = "history.json"
    if not os.path.exists(path):
        return {}, 1, {0: "0"}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    max_t = max([n["turn"] for n in nodes]) if nodes else 1
    marks = {i: str(i) for i in range(0, max_t + 1) if i % 10 == 0 or i == max_t}
    return data, max_t, marks


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
    ctx = callback_context
    trigger = ctx.triggered[0]["prop_id"]

    if "play-button" in trigger:
        is_disabled = n_clicks % 2 == 0
        label = "再生" if is_disabled else "停止"
        return current_range, label, is_disabled

    if "auto-play-interval" in trigger:
        new_max = current_range[1] + 1
        if new_max > max_t:
            return [current_range[0], current_range[1]], "再生", True
        return [current_range[0], new_max], "停止", False

    return current_range, "再生", True


@app.callback(
    Output("cytoscape-tree", "elements"),
    Input("full-data-store", "data"),
    Input("turn-range-slider", "value"),
    Input("visibility-toggle", "value"),
    Input("collapsed-nodes-store", "data"),
    Input("search-button", "n_clicks"),
    Input("left-tabs", "value"),
    State("search-input", "value"),
)
def update_elements(
    data, turn_range, visibility, collapsed_ids, n_search, left_tab, search_query
):
    if left_tab != "tab-tree":
        return dash.no_update
    if not data:
        return []
    inf_value = data.get("INF", 1e18)
    nodes = data.get("nodes", [])

    snapshots_dict = {}
    for s in data.get("snapshots", []):
        snapshots_dict[s["turn"]] = {
            "active": s["active_node_ids"],
            "threshold": s.get("threshold", inf_value),
        }

    nodes_dict = {str(n["node_id"]): n for n in nodes}
    show_pruned = "show_pruned" in visibility
    use_heatmap = "heatmap" in visibility

    min_t, max_t = turn_range
    active_path = set()
    terminals = set(str(x) for x in snapshots_dict.get(max_t, {}).get("active", []))
    curr = list(terminals)
    while curr:
        next_nodes = []
        for nid in curr:
            if nid in nodes_dict:
                active_path.add(nid)
                pid = str(nodes_dict[nid]["parent_id"])
                if pid != "-1" and pid not in active_path:
                    next_nodes.append(pid)
        curr = next_nodes
    active_path.add("-1")

    # メモ化を用いた折りたたみ判定の最適化
    collapsed_set = set(collapsed_ids)
    hidden_memo = {}

    def is_hidden(nid):
        if nid in collapsed_set:
            return True
        if nid in hidden_memo:
            return hidden_memo[nid]

        node = nodes_dict.get(nid)
        if not node:
            return False

        pid = str(node["parent_id"])
        if pid == "-1":
            hidden_memo[nid] = False
            return False

        res = is_hidden(pid)
        hidden_memo[nid] = res
        return res

    elements = [{"data": {"id": "-1", "label": "Start"}, "classes": "status-active"}]
    valid_ids = {"-1"}

    valid_scores = [
        n["score"]
        for n in nodes
        if min_t <= n["turn"] <= max_t and n["score"] < inf_value
    ]
    min_score = min(valid_scores) if valid_scores else 0
    max_score = max(valid_scores) if valid_scores else 1

    def get_heatmap_color(score):
        if score >= inf_value:
            return DARK_THEME["inf"]
        ratio = (
            0.5
            if max_score == min_score
            else (score - min_score) / (max_score - min_score)
        )
        r = int(25 + ratio * 186)
        g = int(118 - ratio * 71)
        b = int(210 - ratio * 163)
        return f"rgb({r}, {g}, {b})"

    for n in nodes:
        nid = str(n["node_id"])
        if not (min_t <= n["turn"] <= max_t):
            continue
        if is_hidden(nid):
            continue

        is_active = nid in active_path
        if not show_pruned and not is_active:
            continue

        cls = (
            "status-invalid"
            if n["status"] == 2
            else ("status-active" if is_active else "status-pruned")
        )
        if nid in collapsed_ids:
            cls += " folded"
        if search_query and (
            search_query in str(n["score"]) or search_query in n.get("action", "")
        ):
            cls += " searched"

        element = {
            "data": {"id": nid, "label": f"T:{n['turn']}\nS:{n['score']}"},
            "classes": cls,
        }
        if use_heatmap:
            element["data"]["bg_color"] = get_heatmap_color(n["score"])
            element["classes"] += " heatmap-node"

        elements.append(element)
        valid_ids.add(nid)

    for n in nodes:
        nid = str(n["node_id"])
        if nid not in valid_ids:
            continue

        pid = str(n["parent_id"])
        if pid in valid_ids:
            elements.append(
                {
                    "data": {
                        "id": f"e{pid}_{nid}",
                        "source": pid,
                        "target": nid,
                        "action": n.get("action", ""),
                    }
                }
            )
        elif nid != "-1":
            elements.append(
                {
                    "data": {
                        "id": f"e_start_{nid}",
                        "source": "-1",
                        "target": nid,
                        "action": "(省略)",
                    },
                    "classes": "dummy-edge",
                }
            )

    return elements


@app.callback(
    Output("all-paths-graph", "figure"),
    [Input("full-data-store", "data"), Input("turn-range-slider", "value")],
)
def update_all_graph(data, turn_range):
    if not data:
        return go.Figure()
    nodes = data.get("nodes", [])
    inf = data.get("INF", 1e18)
    min_t, max_t = turn_range
    nodes_dict = {n["node_id"]: n for n in nodes}
    start_base_score = 0
    if nodes:
        min_scores = [nn["score"] for nn in nodes if nn["turn"] == min_t]
        start_base_score = min(min_scores) if min_scores else nodes[0]["score"]

    x, y = [], []
    for n in nodes:
        if not (min_t <= n["turn"] <= max_t) or n["score"] >= inf:
            continue
        pid = n["parent_id"]
        if pid != -1 and pid in nodes_dict:
            p = nodes_dict[pid]
            x += [p["turn"], n["turn"], None]
            y += [p["score"], n["score"], None]
        elif pid == -1:
            x += [0, n["turn"], None]
            y += [start_base_score, n["score"], None]

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
    [
        Output("node-detail-output", "children"),
        Output("action-path-output", "value"),
        Output("node-state-output", "children"),
        Output("score-history-graph", "figure"),
        Output("cytoscape-tree", "stylesheet"),
    ],
    [Input("cytoscape-tree", "tapNodeData")],
    [State("full-data-store", "data")],
)
def display_node(node_data, data):
    if not node_data or node_data["id"] == "-1":
        # 出力値に空文字列を追加
        return "ノードを選択してください", "", "", go.Figure(), BASE_STYLESHEET
    inf_value = data.get("INF", 1e18)

    all_nodes = data.get("nodes", [])
    valid_scores = [n["score"] for n in all_nodes if n["score"] < inf_value]
    y_range = None
    if valid_scores:
        y_min = min(valid_scores)
        y_max = max(valid_scores)
        y_margin = (y_max - y_min) * 0.05
        if y_margin == 0:
            y_margin = 1
        y_range = [y_min - y_margin, y_max + y_margin]

    snapshots_dict = {
        s["turn"]: {
            "active": s["active_node_ids"],
            "threshold": s.get("threshold", inf_value),
        }
        for s in data.get("snapshots", [])
    }
    nodes_dict = {str(n["node_id"]): n for n in data["nodes"]}

    target = nodes_dict.get(node_data["id"])
    if not target:
        return "Error", "", go.Figure(), BASE_STYLESHEET

    detail = (
        f"ID: {target['node_id']}\n"
        f"Score: {target['score']}\n"
        f"Turn: {target['turn']}\n"
        f"Action: {target.get('action','')}\n"
        f"Status: {target['status']}"
    )
    state_json = json.dumps(target.get("state_info", {}), indent=2, ensure_ascii=False)

    # 祖先パスの取得
    path_ids = []
    curr = str(target["node_id"])
    while curr != "-1":
        path_ids.append(curr)
        curr = str(nodes_dict[curr]["parent_id"]) if curr in nodes_dict else "-1"
    path_ids.append("-1")
    action_seq = "".join(
        [
            nodes_dict[nid].get("action", "")
            for nid in path_ids[::-1]
            if nid in nodes_dict
        ]
    )
    children_dict = {}
    for n in all_nodes:
        pid = str(n["parent_id"])
        nid = str(n["node_id"])
        if pid not in children_dict:
            children_dict[pid] = []
        children_dict[pid].append(nid)

    subtree_node_ids = []
    subtree_edge_ids = []
    queue = [str(target["node_id"])]
    while queue:
        curr_node = queue.pop(0)
        if curr_node != str(target["node_id"]):
            subtree_node_ids.append(curr_node)
        if curr_node in children_dict:
            for child in children_dict[curr_node]:
                subtree_edge_ids.append(f"e{curr_node}_{child}")
                queue.append(child)
    # ------------------------------

    path_scores = [nodes_dict[nid]["score"] for nid in path_ids if nid in nodes_dict]
    path_turns = [nodes_dict[nid]["turn"] for nid in path_ids if nid in nodes_dict]
    path_thresholds = [
        snapshots_dict[t]["threshold"] if t in snapshots_dict else None
        for t in path_turns
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=path_turns[::-1],
            y=path_scores[::-1],
            mode="lines+markers",
            name="ノードスコア",
            line=dict(color="#4fc3f7"),
        )
    )

    val_th_x = []
    val_th_y = []
    for t, th in zip(path_turns[::-1], path_thresholds[::-1]):
        if th is not None and th < inf_value:
            val_th_x.append(t)
            val_th_y.append(th)

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
    )

    new_styles = list(BASE_STYLESHEET)

    # 部分木のノード強調（オレンジ）
    if subtree_node_ids:
        node_selectors = ", ".join([f'node[id="{nid}"]' for nid in subtree_node_ids])
        new_styles.append(
            {
                "selector": node_selectors,
                "style": {
                    "border-width": "3px",
                    "border-color": "#ff9800",
                },
            }
        )

    # 部分木のエッジ強調（オレンジ）
    if subtree_edge_ids:
        edge_selectors = ", ".join([f'edge[id="{eid}"]' for eid in subtree_edge_ids])
        new_styles.append(
            {
                "selector": edge_selectors,
                "style": {
                    "width": 3,
                    "line-color": "#ff9800",
                    "target-arrow-color": "#ff9800",
                },
            }
        )

    # 祖先パスのノード強調（黄色）
    if path_ids:
        node_selectors = ", ".join([f'node[id="{nid}"]' for nid in path_ids])
        new_styles.append(
            {
                "selector": node_selectors,
                "style": {
                    "border-width": "3px",
                    "border-color": DARK_THEME["highlight"],
                },
            }
        )

    # 祖先パスのエッジ強調（黄色）
    path_edges_ids = []
    for i in range(len(path_ids) - 1):
        nid = path_ids[i]
        pid = path_ids[i + 1]
        path_edges_ids.append(f"e{pid}_{nid}")

    if path_edges_ids:
        edge_selectors = ", ".join([f'edge[id="{eid}"]' for eid in path_edges_ids])
        new_styles.append(
            {
                "selector": edge_selectors,
                "style": {
                    "width": 4,
                    "line-color": DARK_THEME["highlight"],
                    "target-arrow-color": DARK_THEME["highlight"],
                },
            }
        )

    return detail, action_seq, state_json, fig, new_styles


@app.callback(
    Output("collapsed-nodes-store", "data"),
    Output("comparison-nodes-store", "data"),
    Output("comparison-output", "children"),
    Input("toggle-fold-button", "n_clicks"),
    Input("fold-all-pruned-button", "n_clicks"),
    Input("add-comparison-button", "n_clicks"),
    Input("clear-comparison-button", "n_clicks"),
    State("cytoscape-tree", "tapNodeData"),
    State("collapsed-nodes-store", "data"),
    State("comparison-nodes-store", "data"),
    State("full-data-store", "data"),
    prevent_initial_call=True,
)
def manage_stores(
    n_fold, n_fold_all, n_add, n_clear, tap_data, collapsed, comparison, full_data
):
    ctx = dash.callback_context
    trigger = ctx.triggered[0]["prop_id"]

    if "clear-comparison-button" in trigger:
        return collapsed, [], "リストは空です"

    if "fold-all-pruned-button" in trigger:
        pruned_ids = [str(n["node_id"]) for n in full_data["nodes"] if n["status"] == 1]
        active_collapsed_pruned = [c for c in collapsed if c in pruned_ids]
        if active_collapsed_pruned:
            collapsed = [c for c in collapsed if c not in pruned_ids]
        else:
            for pid in pruned_ids:
                if pid not in collapsed:
                    collapsed.append(pid)
    else:
        if not tap_data or tap_data["id"] == "-1":
            return collapsed, comparison, dash.no_update

        nid = tap_data["id"]

        if "toggle-fold-button" in trigger:
            if nid in collapsed:
                collapsed.remove(nid)
            else:
                collapsed.append(nid)

        if "add-comparison-button" in trigger:
            if nid not in comparison:
                comparison.append(nid)

    nodes_dict = {str(n["node_id"]): n for n in full_data["nodes"]}
    comp_elements = []
    for cid in comparison:
        node = nodes_dict.get(cid)
        if node:
            comp_elements.append(
                html.Div(
                    style={
                        "border": "1px solid #444",
                        "padding": "10px",
                        "marginBottom": "10px",
                    },
                    children=[
                        html.B(f"Node {cid}"),
                        html.P(f"Score: {node['score']} | Turn: {node['turn']}"),
                        html.P(f"Action: {node.get('action','')}"),
                    ],
                )
            )

    return collapsed, comparison, comp_elements if comp_elements else "リストは空です"


@app.callback(
    Output("hover-action-output", "children"),
    Input("cytoscape-tree", "mouseoverEdgeData"),
)
def display_hover_edge(edge_data):
    if edge_data and "action" in edge_data:
        return f"ホバー中のAction: {edge_data['action']}"
    return ""


# @app.callback(
#     Output("cytoscape-tree", "layout"),
#     Input("left-tabs", "value"),
#     prevent_initial_call=True,
# )
# def redraw_tree_layout(tab_value):
#     if tab_value == "tab-tree":
#         return {
#             "name": "breadthfirst",
#             "roots": "#-1",
#             "directed": True,
#             "spacingFactor": 1.1,
#             "refresh": time.time(),  # 差分を強制的に検知させるダミー値
#         }
#     return dash.no_update

# @app.callback(
#     Output("cytoscape-tree", "layout"),
#     Input("left-tabs", "value"),
#     prevent_initial_call=True,
# )
# def redraw_tree_layout(tab_value):
#     if tab_value == "tab-tree":
#         return {"name": "dagre", "nodeSep": 30, "rankSep": 40, "refresh": time.time()}
#     return dash.no_update


@app.callback(
    Output("cytoscape-tree", "layout"),
    Input("left-tabs", "value"),
    prevent_initial_call=True,
)
def redraw_tree_layout(tab_value):
    import time

    if tab_value == "tab-tree":
        return {
            "name": "dagre",
            "rankDir": "LR",
            "nodeSep": 5,
            "rankSep": 40,
            "spacingFactor": 0.8,
            "refresh": time.time(),
        }
    return dash.no_update


if __name__ == "__main__":
    app.run(debug=True)
