import os
import sys
import json
import shutil
import importlib
import pandas as pd
import plotly.express as px
from datetime import datetime
from dash import Dash, dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State

from .vis_runner import task_manager

BASE_PATH = "ahclib_results/all_tests"
FILE_NAME = "result.csv"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_PATH = os.path.join(CURRENT_DIR, "assets/")
VIS_HTML_PATH = os.path.join(os.getcwd(), "visualizer.html")

def get_ahc_setting(key, default):
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        import ahc_settings
        importlib.reload(ahc_settings)
        return getattr(ahc_settings.AHCSettings, key, default)
    except Exception:
        return default

DIRECTION = get_ahc_setting('direction', 'minimize')

if not os.path.exists(ASSETS_PATH):
    os.makedirs(ASSETS_PATH, exist_ok=True)

css_content = """
body { margin: 0; background-color: #121212; color: #e0e0e0; font-family: system-ui, -apple-system, sans-serif; overflow: hidden; }
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #121212; }
::-webkit-scrollbar-thumb { background: #444; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #666; }

.layout-container { display: flex; height: 100vh; width: 100vw; }

.sidebar-base {
    height: 100vh; background-color: #1e1e1e; border-right: 1px solid #333;
    display: flex; flex-direction: column; z-index: 1000;
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.sidebar-pinned { position: relative; width: 440px; min-width: 440px; transform: translateX(0); }
.sidebar-unpinned {
    position: absolute; left: 0; top: 0; width: 440px; transform: translateX(-425px);
    box-shadow: 2px 0 5px rgba(0,0,0,0.5);
}
.sidebar-unpinned:hover { transform: translateX(0); box-shadow: 10px 0 20px rgba(0,0,0,0.7); }
.sidebar-unpinned::after {
    content: ""; position: absolute; top: 0; right: 0; width: 15px; height: 100%;
    background-color: rgba(255,255,255,0.03); cursor: pointer; border-left: 1px solid #333; transition: opacity 0.3s;
}
.sidebar-unpinned::before {
    content: "▶"; position: absolute; top: 50%; right: 2px; color: #666; font-size: 10px;
    transform: translateY(-50%); pointer-events: none; transition: opacity 0.3s; z-index: 10;
}
.sidebar-unpinned:hover::after, .sidebar-unpinned:hover::before { opacity: 0; pointer-events: none; }

.sidebar-content { width: 440px; padding: 20px; box-sizing: border-box; display: flex; flex-direction: column; height: 100%; }

.main-content {
    flex: 1; display: flex; flex-direction: column; padding: 20px 20px 20px 35px;
    gap: 15px; overflow-y: auto; background-color: #121212;
}

.card { background-color: #1e1e1e; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.5); border: 1px solid #333; }
.btn { padding: 6px 12px; border: 1px solid #444; border-radius: 4px; background-color: #2d2d2d; color: #e0e0e0; cursor: pointer; font-size: 12px; font-weight: bold; }
.btn:hover { background-color: #3a3f47; }
.btn-pin { background: transparent; border: none; color: #888; font-size: 18px; cursor: pointer; transition: color 0.2s; }
.btn-pin:hover { color: #e0e0e0; }

.code-container { position: relative; background-color: #2d2d2d; border: 1px solid #444; border-radius: 4px; padding: 15px; height: 300px; display: flex; }
.code-textarea { width: 100%; height: 100%; background-color: transparent; color: #e0e0e0; border: none; outline: none; font-family: monospace; resize: none; padding: 0; }
.clipboard-btn { position: absolute; top: 10px; right: 20px; font-size: 20px; cursor: pointer; color: #e0e0e0; z-index: 5; }

.dash-dropdown .Select-control { background-color: #2d2d2d !important; border: 1px solid #444 !important; color: #e0e0e0 !important; }
.dash-dropdown .Select-menu-outer { background-color: #2d2d2d !important; border: 1px solid #444 !important; color: #e0e0e0 !important; }
.dash-dropdown .Select-value-label { color: #e0e0e0 !important; }

.custom-tabs { border-bottom: 1px solid #444 !important; }
.custom-tab {
    background-color: #2d2d2d !important; color: #aaa !important;
    border: 1px solid #444 !important; border-bottom: none !important;
    padding: 10px !important; font-size: 13px !important;
}
.custom-tab--selected {
    background-color: #1e1e1e !important; color: #e0e0e0 !important;
    border-bottom: 2px solid #1565c0 !important;
}
"""
with open(os.path.join(ASSETS_PATH, "custom.css"), "w", encoding="utf-8") as f:
    f.write(css_content)

def format_timestamp(ts):
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M").strftime("%Y/%m/%d %H:%M")
    except:
        return ts

def load_data():
    data = []
    if not os.path.exists(BASE_PATH):
        return pd.DataFrame(columns=["filename", "score", "state", "time", "timestamp", "name", "test_id"])

    for folder in sorted(os.listdir(BASE_PATH)):
        folder_path = os.path.join(BASE_PATH, folder)
        csv_path = os.path.join(folder_path, FILE_NAME)
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            df["timestamp"] = folder
            df["name"] = df["filename"].str.extract(r"(\d{4}\.txt)")
            df["test_id"] = df["filename"].str.extract(r"(\d{4}\.txt)")
            data.append(df)

    if not data:
        return pd.DataFrame(columns=["filename", "score", "state", "time", "timestamp", "name", "test_id"])

    return pd.concat(data, ignore_index=True)


def load_single_err_out(timestamp, filename):
    err_path = os.path.join(BASE_PATH, timestamp, "err", filename)
    out_path = os.path.join(BASE_PATH, timestamp, "out", filename)

    err_text = "(errファイルなし)"
    out_text = "(outファイルなし)"

    if os.path.exists(err_path):
        with open(err_path, "r", encoding="utf-8", errors="ignore") as f:
            err_text = f.read()
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            out_text = f.read()

    return err_text, out_text


def load_in_file_content(filename):
    in_path = os.path.join("./in", filename)
    if os.path.exists(in_path):
        try:
            with open(in_path, "r", encoding="utf-8") as f:
                return f.read()
        except:
            return ""
    return ""


_CACHE_META_DATA = None
_CACHE_IN_FILES = []
_CACHE_SETTINGS_MTIME = 0

def load_meta_data():
    global _CACHE_META_DATA, _CACHE_IN_FILES, _CACHE_SETTINGS_MTIME
    in_dir = "./in"
    if not os.path.exists(in_dir):
        return pd.DataFrame(columns=["test_id", "Param"])

    current_files = sorted([f for f in os.listdir(in_dir) if f.endswith(".txt")])
    settings_path = os.path.join(os.getcwd(), "ahc_settings.py")
    current_settings_mtime = os.path.getmtime(settings_path) if os.path.exists(settings_path) else 0

    if _CACHE_META_DATA is not None and _CACHE_IN_FILES == current_files and _CACHE_SETTINGS_MTIME == current_settings_mtime:
        return _CACHE_META_DATA.copy()

    meta = []
    custom_parser = None
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        import ahc_settings
        importlib.reload(ahc_settings)
        if hasattr(ahc_settings.AHCSettings, 'parse_input_params'):
            custom_parser = ahc_settings.AHCSettings.parse_input_params
    except Exception:
        pass

    for fname in current_files:
        path = os.path.join(in_dir, fname)
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
                nums = [int(x) for x in line.split() if x.lstrip('-').isdigit()]
                param = float(nums[0]) if nums else float(os.path.getsize(path))
            meta.append({"test_id": fname, "Param": param})
        except Exception:
            meta.append({"test_id": fname, "Param": 0.0})

    if meta:
        _CACHE_META_DATA = pd.DataFrame(meta)
    else:
        _CACHE_META_DATA = pd.DataFrame(columns=["test_id", "Param"])

    _CACHE_IN_FILES = current_files
    _CACHE_SETTINGS_MTIME = current_settings_mtime

    return _CACHE_META_DATA.copy()


app = Dash(__name__, assets_folder=ASSETS_PATH)

app.layout = html.Div(className="layout-container", children=[
    dcc.Store(id="base-store"),
    dcc.Store(id="table-data", data=[]),

    dcc.Interval(id="task-interval", interval=10000, n_intervals=0),
    dcc.Store(id="task-was-running", data=False),

    # === 左側：サイドバー ===
    html.Div(id="sidebar-container", className="sidebar-base sidebar-unpinned", children=[
        html.Div(className="sidebar-content", children=[
            html.Div(style={"display": "flex", "alignItems": "center", "marginBottom": "15px", "justifyContent": "space-between"}, children=[
                html.H2("AHC Dashboard", style={"margin": "0", "fontSize": "20px"}),
                html.Button("📌", id="pin-btn", className="btn-pin", title="サイドバーを固定する")
            ]),

            html.Div(className="card", style={"padding": "15px", "marginBottom": "20px", "backgroundColor": "#252525", "boxShadow": "inset 0 2px 4px rgba(0,0,0,0.5)"}, children=[
                html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "12px"}, children=[
                    html.H3("Runner Queue", style={"margin": "0", "fontSize": "14px", "color": "#ccc"}),
                ]),
                html.Div(style={"display": "flex", "gap": "6px", "marginBottom": "10px"}, children=[
                    html.Button("▶ Test", id="btn-run-test", className="btn", style={"flex": "1", "backgroundColor": "#2e7d32", "borderColor": "#1b5e20", "color": "white"}),
                    html.Button("▶ Opt", id="btn-run-opt", className="btn", style={"flex": "1", "backgroundColor": "#1565c0", "borderColor": "#0d47a1", "color": "white"}),
                    html.Button("⏹ Stop", id="btn-stop-task", className="btn", style={"flex": "1", "backgroundColor": "#c62828", "borderColor": "#b71c1c", "color": "white"}),
                    html.Button("🗑️ Clear", id="btn-clear-queue", className="btn", style={"flex": "1", "backgroundColor": "#555", "borderColor": "#333", "color": "white"}),
                ]),
                html.Div(id="queue-display", style={"fontSize": "12px", "color": "#aaa", "whiteSpace": "pre-wrap", "fontFamily": "monospace", "lineHeight": "1.5"})
            ]),

            html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "8px", "marginBottom": "10px"}, children=[
                html.Button("🔄 更新", id="reload-button", className="btn", n_clicks=0),
                html.Button("🆕 直近を追加", id="add-latest", className="btn", n_clicks=0),
                html.Button("✅ 全選択", id="select-all", className="btn", n_clicks=0),
                html.Button("❌ 解除", id="clear-selection", className="btn", n_clicks=0),
            ]),

            html.Div(style={"flex": "1", "overflowY": "auto"}, children=[
                dash_table.DataTable(
                    id="timestamp-table",
                    columns=[
                        {"name": "Base", "id": "is_base_str"},
                        {"name": "実行日時", "id": "formatted"},
                        {"name": "Ave", "id": "average_score", "type": "numeric", "format": {"specifier": ".2f"}},
                        {"name": "Rel", "id": "rel_ave", "type": "numeric", "format": {"specifier": ".3f"}},
                        {"name": "", "id": "delete_btn"},
                    ],
                    style_table={"width": "100%"},
                    style_cell={"textAlign": "left", "padding": "6px", "fontSize": "12px", "backgroundColor": "#1e1e1e", "color": "#e0e0e0", "border": "1px solid #444"},
                    style_header={"fontWeight": "bold", "backgroundColor": "#2d2d2d", "color": "#e0e0e0", "border": "1px solid #444"},
                    style_data_conditional=[
                        {"if": {"state": "selected"}, "backgroundColor": "#3a3f47", "border": "1px solid #666"},
                        {"if": {"state": "active"}, "backgroundColor": "#3a3f47", "border": "1px solid #666"},

                        {"if": {"column_id": "is_base_str"}, "cursor": "pointer", "textAlign": "center", "width": "40px", "fontSize": "14px"},
                        {"if": {"column_id": "is_base_str", "filter_query": "{is_base_str} = '★'"}, "color": "#ffca28"},
                        {"if": {"column_id": "is_base_str", "filter_query": "{is_base_str} = '・'"}, "color": "#666666"},
                        {"if": {"column_id": "delete_btn"}, "cursor": "pointer", "textAlign": "center", "width": "30px", "fontSize": "14px", "color": "#e57373"},

                        {
                            "if": {
                                "column_id": "rel_ave",
                                "filter_query": "{rel_ave} < 1.0" if DIRECTION == "minimize" else "{rel_ave} > 1.0"
                            },
                            "backgroundColor": "rgba(46, 125, 50, 0.3)", "color": "#81c784"
                        },
                        {
                            "if": {
                                "column_id": "rel_ave",
                                "filter_query": "{rel_ave} > 1.0" if DIRECTION == "minimize" else "{rel_ave} < 1.0"
                            },
                            "backgroundColor": "rgba(183, 28, 28, 0.3)", "color": "#e57373"
                        },
                    ],
                    row_selectable="multi",
                    selected_rows=[],
                )
            ])
        ])
    ]),

    # === 右側：メインコンテンツ ===
    html.Div(className="main-content", children=[

        # 上部：グラフエリア
        html.Div(className="card", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px", "flexWrap": "wrap", "gap": "10px"}, children=[
                html.Div(id="summary-text", style={"fontWeight": "bold", "color": "#ccc", "minWidth": "150px"}),

                html.Div(style={"display": "flex", "alignItems": "center", "gap": "15px", "flexWrap": "wrap"}, children=[
                    dcc.RadioItems(
                        id="graph-type",
                        options=[
                            {"label": html.Span("絶対スコア", style={"paddingLeft": "4px"}), "value": "abs"},
                            {"label": html.Span("相対スコア", style={"paddingLeft": "4px"}), "value": "rel"},
                            {"label": html.Span("全体の箱ひげ図", style={"paddingLeft": "4px"}), "value": "box"},
                            {"label": html.Span("相関(散布図)", style={"paddingLeft": "4px"}), "value": "param_scatter"},
                            {"label": html.Span("相関(Box)", style={"paddingLeft": "4px"}), "value": "param_box"},
                            {"label": html.Span("相関(平均)", style={"paddingLeft": "4px"}), "value": "param_line"},
                        ],
                        value="abs",
                        inline=True,
                        style={"display": "flex", "gap": "12px"},
                        labelStyle={"cursor": "pointer", "color": "#e0e0e0", "display": "flex", "alignItems": "center", "fontSize": "13px"}
                    ),
                    html.Div(id="param-selector-container", children=[
                        dcc.Dropdown(
                            id="param-selector",
                            options=[],
                            clearable=False,
                            style={"width": "120px", "color": "#333"},
                            className="dash-dropdown"
                        )
                    ], style={"display": "none"}),
                    dcc.Checklist(
                        id="log-scale-check",
                        options=[{"label": html.Span(" Y軸をLogスケール", style={"paddingLeft": "4px", "color": "#e0e0e0"}), "value": "log"}],
                        value=[],
                        labelStyle={"cursor": "pointer", "display": "flex", "alignItems": "center"},
                        style={"fontSize": "13px"}
                    )
                ])
            ]),
            dcc.Graph(id="score-comparison-graph", style={"height": "350px"})
        ]),

        # 下部：詳細エリア
        html.Div(className="card", style={"display": "flex", "gap": "20px", "flex": "1", "padding": "0", "overflow": "hidden", "minHeight": "400px"}, children=[

            html.Div(style={"flex": "1", "minWidth": "250px", "display": "flex", "flexDirection": "column", "borderRight": "1px solid #333", "padding": "20px"}, children=[
                html.Div(id="current-timestamp-display", style={"fontWeight": "bold", "marginBottom": "10px", "color": "#ccc", "flexShrink": "0"}),
                html.Div(style={"flex": "1", "overflowY": "auto", "minHeight": "0"}, children=[
                    dash_table.DataTable(
                        id="file-name-table",
                        columns=[
                            {"name": "Case", "id": "name"},
                            {"name": "Score", "id": "score"},
                            {"name": "Time", "id": "time", "type": "numeric", "format": {"specifier": ".3f"}},
                        ],
                        sort_action="native",
                        style_cell={"textAlign": "left", "padding": "8px", "fontFamily": "monospace", "fontSize": "13px", "backgroundColor": "#1e1e1e", "color": "#e0e0e0", "border": "1px solid #444"},
                        style_header={"fontWeight": "bold", "backgroundColor": "#2d2d2d", "color": "#e0e0e0", "border": "1px solid #444"},
                        cell_selectable=True,
                        style_as_list_view=True,
                    )
                ])
            ]),

            html.Div(style={"flex": "3", "display": "flex", "flexDirection": "column", "height": "100%", "minWidth": "0"}, children=[
                dcc.Tabs(id="detail-tabs", value="tab-text", className="custom-tabs", children=[
                    dcc.Tab(label="標準出力 (err/out)", value="tab-text", className="custom-tab", selected_className="custom-tab--selected"),
                    dcc.Tab(label="ビジュアライザ", value="tab-vis", className="custom-tab", selected_className="custom-tab--selected"),
                ]),
                html.Div(id="tab-content", style={"flex": "1", "padding": "20px", "overflowY": "auto", "display": "flex", "flexDirection": "column", "minHeight": "0"})
            ])
        ])
    ])
])

# --- コールバック ---
@app.callback(
    Output("queue-display", "children"),
    Input("btn-run-test", "n_clicks"),
    Input("btn-run-opt", "n_clicks"),
    Input("btn-stop-task", "n_clicks"),
    Input("btn-clear-queue", "n_clicks"),
    Input("task-interval", "n_intervals"),
    prevent_initial_call=False
)
def update_queue(n_test, n_opt, n_stop, n_clear, n_intervals):
    triggered = ctx.triggered_id
    if triggered == "btn-run-test":
        task_manager.add_test()
    elif triggered == "btn-run-opt":
        task_manager.add_opt()
    elif triggered == "btn-stop-task":
        task_manager.stop_current()
    elif triggered == "btn-clear-queue":
        task_manager.clear_queue()

    status = task_manager.get_queue_status()

    lines = []
    if status["current"]:
        lines.append(f"🟢 [Running] {status['current']['type'].upper()} (sent: {status['current']['time']})")
    else:
        lines.append("⚪ [Idle] 待機中")

    for i, q in enumerate(status["queue"]):
        lines.append(f"⏳ [Queue {i+1}] {q['type'].upper()} (sent: {q['time']})")

    return "\n".join(lines)


@app.callback(
    Output("reload-button", "n_clicks"),
    Output("task-was-running", "data"),
    Input("task-interval", "n_intervals"),
    State("task-was-running", "data"),
    State("reload-button", "n_clicks"),
)
def auto_reload_on_finish(n_int, was_running, reload_clicks):
    status = task_manager.get_queue_status()
    is_running = status["current"] is not None
    clicks = reload_clicks or 0
    if was_running and not is_running:
        clicks += 1
    return clicks, is_running


@app.callback(
    Output("sidebar-container", "className"),
    Output("pin-btn", "children"),
    Output("pin-btn", "title"),
    Input("pin-btn", "n_clicks"),
    State("sidebar-container", "className")
)
def toggle_sidebar_pin(n_clicks, current_class):
    if n_clicks is None: return current_class, "📌", "サイドバーを固定する"
    if "sidebar-unpinned" in current_class:
        return "sidebar-base sidebar-pinned", "◀", "サイドバーの固定を解除する"
    else:
        return "sidebar-base sidebar-unpinned", "📌", "サイドバーを固定する"

@app.callback(
    Output("param-selector-container", "style"),
    Input("graph-type", "value")
)
def toggle_param_selector(graph_type):
    if graph_type in ["param_scatter", "param_box", "param_line"]:
        return {"display": "block"}
    return {"display": "none"}

@app.callback(
    Output("param-selector", "options"),
    Output("param-selector", "value"),
    Input("reload-button", "n_clicks"),
    State("param-selector", "value")
)
def update_param_options(n, current_value):
    meta_df = load_meta_data()
    cols = [c for c in meta_df.columns if c != "test_id"]
    if not cols: return [], None

    options = [{"label": c, "value": c} for c in cols]

    if current_value in cols:
        return options, current_value
    return options, cols[0]

@app.callback(
    Output("base-store", "data"),
    Input("timestamp-table", "active_cell"),
    State("table-data", "data"),
    State("base-store", "data")
)
def update_base_store(active_cell, table_data, current_base):
    if not active_cell or not table_data: return current_base
    if active_cell["column_id"] == "is_base_str":
        row_idx = active_cell["row"]
        if row_idx < len(table_data):
            return table_data[row_idx]["timestamp"]
    return current_base

@app.callback(
    Output("timestamp-table", "data"),
    Output("table-data", "data"),
    Input("reload-button", "n_clicks"),
    Input("base-store", "data"),
    Input("timestamp-table", "active_cell"),
    State("table-data", "data")
)
def update_table(n, base_ts, active_cell, current_data):
    triggered = ctx.triggered_id

    if triggered == "timestamp-table" and active_cell and active_cell.get("column_id") == "delete_btn":
        row_idx = active_cell["row"]
        if current_data and row_idx < len(current_data):
            ts_to_delete = current_data[row_idx]["timestamp"]
            dir_path = os.path.join(BASE_PATH, ts_to_delete)
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)

    df = load_data()
    if df.empty: return [], []

    timestamps = sorted(df["timestamp"].unique())
    if not timestamps: return [], []

    if base_ts not in timestamps:
        base_ts = timestamps[0]

    base_df = df[df["timestamp"] == base_ts][["test_id", "score"]].rename(columns={"score": "base_score"})
    merged = pd.merge(df, base_df, on="test_id", how="left")

    merged["rel_score"] = merged.apply(
        lambda r: r["score"] / r["base_score"] if pd.notna(r["base_score"]) and r["base_score"] != 0 else 1.0,
        axis=1
    )

    grouped = merged.groupby("timestamp").agg(
        average_score=("score", "mean"),
        rel_ave=("rel_score", "mean")
    ).reset_index()

    grouped["formatted"] = grouped["timestamp"].apply(format_timestamp)
    grouped["is_base_str"] = grouped["timestamp"].apply(lambda ts: "★" if ts == base_ts else "・")
    grouped["delete_btn"] = "🗑️"
    grouped = grouped.sort_values("timestamp")

    records = grouped.to_dict("records")
    return records, records


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
    if not data: return []

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
    Input("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def show_current_timestamp(selected_rows, table_data):
    valid_rows = [r for r in selected_rows if r < len(table_data)] if selected_rows else []
    if not valid_rows or not table_data:
        return "テストケース詳細 (選択されていません)"
    latest_ts = table_data[valid_rows[-1]]["timestamp"]
    return f"詳細表示: {latest_ts}"

@app.callback(
    Output("score-comparison-graph", "figure"),
    Output("summary-text", "children"),
    Input("timestamp-table", "selected_rows"),
    Input("graph-type", "value"),
    Input("param-selector", "value"),
    Input("log-scale-check", "value"), # ← 追加
    State("table-data", "data"),
    State("base-store", "data")
)
def update_graph(rows, graph_type, param_col, log_scale, table_data, base_ts):
    valid_rows = [r for r in rows if r < len(table_data)] if rows else []
    if not valid_rows:
        fig = px.line(title="（実行結果が選択されていません）")
        fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=40, b=20), paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        return fig, "比較グラフ: 選択中 0 件"

    selected_timestamps = [table_data[i]["timestamp"] for i in valid_rows]
    df_all = load_data()
    df = df_all[df_all["timestamp"].isin(selected_timestamps)]
    df = df[pd.to_numeric(df["score"], errors="coerce").notna()]
    if not df.empty:
        df["score"] = df["score"].astype(float)

    if df.empty:
        fig = px.line(title="（表示するデータがありません）")
    else:
        sorted_ts = sorted(selected_timestamps)

        if graph_type == "abs":
            fig = px.line(df, x="test_id", y="score", color="timestamp", markers=True, category_orders={"timestamp": sorted_ts})
            fig.update_layout(yaxis_title="Score")

        elif graph_type == "rel":
            if base_ts not in df_all["timestamp"].values:
                base_ts = sorted_ts[0]
            base_df = df_all[df_all["timestamp"] == base_ts][["test_id", "score"]].rename(columns={"score": "base_score"})
            merged = pd.merge(df, base_df, on="test_id", how="left")
            merged["relative_score"] = merged.apply(lambda r: r["score"] / r["base_score"] if pd.notna(r["base_score"]) and r["base_score"] != 0 else 1.0, axis=1)
            fig = px.line(merged, x="test_id", y="relative_score", color="timestamp", markers=True, category_orders={"timestamp": sorted_ts})
            fig.add_hline(y=1.0, line_dash="dash", line_color="#888", annotation_text=f"Base: {base_ts}")
            fig.update_layout(yaxis_title="Relative Score")

        elif graph_type == "box":
            fig = px.box(df, x="timestamp", y="score", color="timestamp", category_orders={"timestamp": sorted_ts})
            fig.update_layout(xaxis_title="Execution", yaxis_title="Score")

        elif graph_type.startswith("param_"):
            meta_df = load_meta_data()
            if not meta_df.empty and param_col in meta_df.columns:
                merged = pd.merge(df, meta_df, on="test_id", how="left")
                if graph_type == "param_scatter":
                    fig = px.scatter(merged, x=param_col, y="score", color="timestamp", hover_data=["test_id"], category_orders={"timestamp": sorted_ts})
                elif graph_type == "param_box":
                    fig = px.box(merged, x=param_col, y="score", color="timestamp", category_orders={"timestamp": sorted_ts})
                elif graph_type == "param_line":
                    avg_df = merged.groupby([param_col, "timestamp"])["score"].mean().reset_index()
                    fig = px.line(avg_df, x=param_col, y="score", color="timestamp", markers=True, category_orders={"timestamp": sorted_ts})
                fig.update_layout(xaxis_title=f"Parameter: {param_col}", yaxis_title="Score")
            else:
                fig = px.scatter(title="（パラメータ情報を取得できませんでした）")
                fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")

    # --- 対数スケールの適用判定 ---
    is_log = bool(log_scale and "log" in log_scale)

    fig.update_layout(
        template="plotly_dark",
        hovermode="x unified" if graph_type in ["abs", "rel"] else "closest",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="#1e1e1e",
        plot_bgcolor="#1e1e1e",
        uirevision=True,
        yaxis_type="log" if is_log else "linear"  # ← 追加：Logの切り替え
    )
    return fig, f"比較グラフ: 選択中 {len(selected_timestamps)} 件"

@app.callback(
    Output("file-name-table", "data"),
    Input("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def update_file_table(selected_rows, table_data):
    valid_rows = [r for r in selected_rows if r < len(table_data)] if selected_rows else []
    if not valid_rows or not table_data: return []
    timestamp = table_data[valid_rows[-1]]["timestamp"]
    df = load_data()
    df = df[df["timestamp"] == timestamp]
    df["time"] = pd.to_numeric(df["time"], errors="coerce")
    return df[["name", "score", "time"]].to_dict("records")

@app.callback(
    Output("tab-content", "children"),
    Input("detail-tabs", "value"),
    Input("file-name-table", "active_cell"),
    State("file-name-table", "data"),
    State("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def render_tab_content(tab, active_cell, file_data, ts_rows, ts_data):
    if not active_cell or not file_data or not ts_rows or not ts_data:
        return html.Div("ファイルが選択されていません。", style={"color": "#ccc"})

    filename = file_data[active_cell["row"]]["name"]
    valid_rows = [r for r in ts_rows if r < len(ts_data)]
    if not valid_rows: return html.Div("データが見つかりません。", style={"color": "#ccc"})
    timestamp = ts_data[valid_rows[-1]]["timestamp"]

    if tab == "tab-text":
        err_text, out_text = load_single_err_out(timestamp, filename)

        return html.Div(style={"display": "flex", "flexDirection": "column", "gap": "20px", "height": "100%"}, children=[
            html.Div(style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "0"}, children=[
                html.H4("標準エラー出力 (err)", style={"margin": "0 0 10px 0", "color": "#ccc"}),
                html.Div(className="code-container", style={"flex": "1"}, children=[
                    dcc.Clipboard(content=err_text, className="clipboard-btn"),
                    dcc.Textarea(value=err_text, className="code-textarea", readOnly=True)
                ])
            ]),
            html.Div(style={"flex": "1", "display": "flex", "flexDirection": "column", "minHeight": "0"}, children=[
                html.H4("標準出力 (out)", style={"margin": "0 0 10px 0", "color": "#ccc"}),
                html.Div(className="code-container", style={"flex": "1"}, children=[
                    dcc.Clipboard(content=out_text, className="clipboard-btn"),
                    dcc.Textarea(value=out_text, className="code-textarea", readOnly=True)
                ])
            ])
        ])

    elif tab == "tab-vis":
        in_text = load_in_file_content(filename)
        _, out_text = load_single_err_out(timestamp, filename)
        if out_text == "(outファイルなし)":
            out_text = ""

        if os.path.exists(VIS_HTML_PATH):
            with open(VIS_HTML_PATH, "r", encoding="utf-8") as f:
                html_template = f.read()

            js_data_block = f"<script>\nconst INPUT_DATA = {json.dumps(in_text)};\nconst OUTPUT_DATA = {json.dumps(out_text)};\n</script>"
            src_doc = html_template.replace("</body>", f"{js_data_block}\n</body>")

            return html.Iframe(srcDoc=src_doc, style={"width": "100%", "height": "100%", "border": "none", "backgroundColor": "#fff"})
        else:
            return html.Div("ビジュアライザのHTMLファイルが見つかりません。", style={"color": "#e57373", "fontWeight": "bold", "padding": "20px"})

if __name__ == "__main__":
    app.run(debug=False)
