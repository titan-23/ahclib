import os
import sys
import json
import shutil
import importlib
import difflib
import re
import pandas as pd
import plotly.express as px
import dash
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

input[type="radio"], input[type="checkbox"] { accent-color: #29b6f6; cursor: pointer; }

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
.code-textarea { width: 100%; height: 100%; background-color: transparent; color: #e0e0e0; border: none; outline: none; font-family: monospace; resize: none; padding: 0; white-space: pre; overflow-wrap: normal; overflow-x: auto; }
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
    border-bottom: 2px solid #29b6f6 !important;
}
"""
with open(os.path.join(ASSETS_PATH, "custom.css"), "w", encoding="utf-8") as f:
    f.write(css_content)

def format_timestamp(ts):
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M").strftime("%Y/%m/%d %H:%M")
    except:
        return ts

_CSV_CACHE = {}

def load_data():
    global _CSV_CACHE
    data = []
    empty_df = pd.DataFrame(columns=["filename", "score", "state", "time", "timestamp", "name", "test_id"])

    if not os.path.exists(BASE_PATH):
        return empty_df

    current_folders = sorted(os.listdir(BASE_PATH))
    _CSV_CACHE = {k: v for k, v in _CSV_CACHE.items() if os.path.basename(k) in current_folders}

    for folder in current_folders:
        folder_path = os.path.join(BASE_PATH, folder)
        csv_path = os.path.join(folder_path, FILE_NAME)

        if os.path.exists(csv_path):
            try:
                mtime = os.path.getmtime(csv_path)
                if folder_path in _CSV_CACHE and _CSV_CACHE[folder_path][0] == mtime:
                    df = _CSV_CACHE[folder_path][1]
                else:
                    df = pd.read_csv(csv_path)
                    df["timestamp"] = folder
                    df["name"] = df["filename"].str.extract(r"(\d{4}\.txt)")
                    df["test_id"] = df["filename"].str.extract(r"(\d{4}\.txt)")
                    _CSV_CACHE[folder_path] = (mtime, df)
                data.append(df)
            except Exception:
                pass

    if not data:
        return empty_df

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

def load_source_code(timestamp):
    """保存された ahc_settings.py と同ディレクトリのソースコードを取得する"""
    dir_path = os.path.join(BASE_PATH, timestamp)
    settings_path = os.path.join(dir_path, "ahc_settings.py")
    src_filename = None

    # 1. ahc_settings.py から filename 変数を探す
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                content = f.read()
                m = re.search(r'filename\s*=\s*["\'](.*?)["\']', content)
                if m:
                    src_filename = os.path.basename(m.group(1))
        except: pass

    # 2. 見つからない場合はディレクトリ内のソースっぽいファイルを探す
    if not src_filename and os.path.exists(dir_path):
        for f in os.listdir(dir_path):
            if (f.endswith(".cpp") or f.endswith(".py") or f.endswith(".rs")) \
               and f not in ["ahc_settings.py", "result.csv"]:
                src_filename = f
                break

    if not src_filename:
        src_filename = "main.cpp"

    src_path = os.path.join(dir_path, src_filename)
    if os.path.exists(src_path):
        with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(), src_filename

    # 古い保存形式のフォールバック (e.g. "./main.cpp" と保存されていた場合)
    fallback_path = os.path.join(dir_path, ".", src_filename)
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(), src_filename

    return "(ソースコードが保存されていません)", src_filename

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
    dcc.Store(id="prev-selected-rows", data=[]),
    dcc.Store(id="target-ts-store", data=None),
    html.Div(id="dummy-output", style={"display": "none"}),

    dcc.Interval(id="task-interval", interval=10000, n_intervals=0),
    dcc.Store(id="task-was-running", data=False),

    # === 左側：サイドバー ===
    html.Div(id="sidebar-container", className="sidebar-base sidebar-pinned", children=[
        html.Div(className="sidebar-content", children=[
            html.Div(style={"display": "flex", "alignItems": "center", "marginBottom": "15px", "justifyContent": "space-between"}, children=[
                html.H2("AHC Dashboard", style={"margin": "0", "fontSize": "20px"}),
                html.Button("◀", id="pin-btn", className="btn-pin", title="サイドバーの固定を解除する")
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
                        {"name": "Memo", "id": "memo", "editable": True},
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
                        {"if": {"column_id": "memo"}, "maxWidth": "80px", "textOverflow": "ellipsis", "overflow": "hidden", "whiteSpace": "nowrap", "backgroundColor": "#2a2a2a"},

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
            ]),
            html.Div("※ Memo列をクリックでメモを編集・自動保存できます", style={"fontSize": "11px", "color": "#888", "marginTop": "5px"})
        ])
    ]),

    # === 右側：メインコンテンツ ===
    html.Div(className="main-content", children=[

        html.Div(className="card", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px", "flexWrap": "wrap", "gap": "10px"}, children=[
                html.Div(id="summary-text", style={"fontWeight": "bold", "color": "#ccc", "minWidth": "150px"}),

                html.Div(style={"display": "flex", "alignItems": "center", "gap": "15px", "flexWrap": "wrap"}, children=[
                    dcc.RadioItems(
                        id="graph-type",
                        options=[
                            {"label": html.Span("絶対スコア", style={"paddingLeft": "4px"}), "value": "abs"},
                            {"label": html.Span("相対スコア", style={"paddingLeft": "4px"}), "value": "rel"},
                            {"label": html.Span("箱ひげ図", style={"paddingLeft": "4px"}), "value": "box"},
                            {"label": html.Span("相関(散布図)", style={"paddingLeft": "4px"}), "value": "param_scatter"},
                            {"label": html.Span("相関(Box)", style={"paddingLeft": "4px"}), "value": "param_box"},
                            {"label": html.Span("相関(平均)", style={"paddingLeft": "4px"}), "value": "param_line"},
                            {"label": html.Span("HM(絶対)", style={"paddingLeft": "4px"}), "value": "heatmap_abs"},
                            {"label": html.Span("HM(相対)", style={"paddingLeft": "4px"}), "value": "heatmap_rel"},
                        ],
                        value="abs",
                        inline=True,
                        style={"display": "flex", "gap": "12px"},
                        labelStyle={"cursor": "pointer", "color": "#e0e0e0", "display": "flex", "alignItems": "center", "fontSize": "13px"}
                    ),
                    html.Div(id="param-selector-container", style={"display": "none", "alignItems": "center", "gap": "5px"}, children=[
                        html.Div(id="param-y-wrapper", style={"display": "none", "alignItems": "center", "gap": "5px"}, children=[
                            dcc.Dropdown(id="param-selector-y", options=[], clearable=False, style={"width": "80px", "color": "#333"}, className="dash-dropdown"),
                            html.Span("×", style={"color": "#aaa", "paddingBottom": "2px"})
                        ]),
                        dcc.Dropdown(id="param-selector", options=[], clearable=False, style={"width": "80px", "color": "#333"}, className="dash-dropdown")
                    ]),
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

        html.Div(className="card", style={"display": "flex", "gap": "20px", "flex": "1", "padding": "0", "overflow": "hidden", "minHeight": "400px"}, children=[

            html.Div(style={"flex": "1", "minWidth": "250px", "display": "flex", "flexDirection": "column", "borderRight": "1px solid #333", "padding": "20px"}, children=[
                html.Div(id="current-timestamp-display", style={"fontWeight": "bold", "marginBottom": "10px", "color": "#ccc", "flexShrink": "0"}),
                html.Div(style={"flex": "1", "overflowY": "auto", "minHeight": "0"}, children=[
                    dash_table.DataTable(
                        id="file-name-table",
                        columns=[
                            {"name": "Case", "id": "name"},
                            {"name": "Score", "id": "score", "type": "numeric"},
                            {"name": "Time", "id": "time", "type": "numeric", "format": {"specifier": ".3f"}},
                            {"name": "Best", "id": "best", "type": "numeric"},
                            {"name": "Rel", "id": "rel", "type": "numeric", "format": {"specifier": ".3f"}},
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
                    dcc.Tab(label="Diff (ソースコード)", value="tab-diff", className="custom-tab", selected_className="custom-tab--selected"),
                    dcc.Tab(label="ビジュアライザ", value="tab-vis", className="custom-tab", selected_className="custom-tab--selected"),
                ]),
                html.Div(id="tab-content", style={"flex": "1", "padding": "20px", "overflowY": "auto", "display": "flex", "flexDirection": "column", "minHeight": "0"})
            ])
        ])
    ])
])


@app.callback(
    Output("target-ts-store", "data"),
    Output("prev-selected-rows", "data"),
    Input("timestamp-table", "selected_rows"),
    State("prev-selected-rows", "data"),
    State("target-ts-store", "data"),
    State("table-data", "data")
)
def update_target_store(selected_rows, prev_selected, current_target, table_data):
    if selected_rows is None: selected_rows = []
    if prev_selected is None: prev_selected = []
    if not table_data: return None, selected_rows

    added = [r for r in selected_rows if r not in prev_selected]
    new_target = current_target

    if added:
        last_added = added[-1]
        if last_added < len(table_data):
            new_target = table_data[last_added]["timestamp"]
    else:
        selected_ts_list = [table_data[r]["timestamp"] for r in selected_rows if r < len(table_data)]
        if new_target not in selected_ts_list:
            if selected_ts_list:
                new_target = sorted(selected_ts_list)[-1]
            else:
                new_target = None

    return new_target, selected_rows


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
    State("sidebar-container", "className"),
    prevent_initial_call=True
)
def toggle_sidebar_pin(n_clicks, current_class):
    if "sidebar-unpinned" in current_class:
        return "sidebar-base sidebar-pinned", "◀", "サイドバーの固定を解除する"
    else:
        return "sidebar-base sidebar-unpinned", "📌", "サイドバーを固定する"

@app.callback(
    Output("param-selector-container", "style"),
    Output("param-y-wrapper", "style"),
    Input("graph-type", "value")
)
def toggle_param_selector(graph_type):
    if graph_type in ["heatmap_abs", "heatmap_rel"]:
        return {"display": "flex", "alignItems": "center", "gap": "5px"}, {"display": "flex", "alignItems": "center", "gap": "5px"}
    elif graph_type in ["param_scatter", "param_box", "param_line"]:
        return {"display": "flex", "alignItems": "center", "gap": "5px"}, {"display": "none"}
    return {"display": "none"}, {"display": "none"}

@app.callback(
    Output("param-selector", "options"),
    Output("param-selector", "value"),
    Output("param-selector-y", "options"),
    Output("param-selector-y", "value"),
    Input("reload-button", "n_clicks"),
    State("param-selector", "value"),
    State("param-selector-y", "value")
)
def update_param_options(n, current_x, current_y):
    meta_df = load_meta_data()
    cols = [c for c in meta_df.columns if c != "test_id"]
    if not cols: return [], None, [], None

    options = [{"label": c, "value": c} for c in cols]

    val_x = current_x if current_x in cols else cols[0]
    val_y = current_y if current_y in cols else (cols[1] if len(cols) > 1 else cols[0])

    return options, val_x, options, val_y

@app.callback(
    Output("base-store", "data"),
    Input("timestamp-table", "active_cell"),
    State("table-data", "data"),
    State("base-store", "data")
)
def update_base_store(active_cell, table_data, current_base):
    if not active_cell or not table_data: return current_base
    if active_cell["column_id"] == "is_base_str":
        base_ts = active_cell.get("row_id")
        if base_ts:
            return base_ts
        row_idx = active_cell["row"]
        if row_idx < len(table_data):
            return table_data[row_idx]["timestamp"]
    return current_base

def get_memo(ts):
    memo_path = os.path.join(BASE_PATH, ts, "memo.txt")
    if os.path.exists(memo_path):
        try:
            with open(memo_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except: pass
    return ""

@app.callback(
    Output("dummy-output", "children"),
    Input("timestamp-table", "data"),
    State("timestamp-table", "data_previous"),
    prevent_initial_call=True
)
def save_memo(current_data, previous_data):
    if current_data and previous_data:
        for curr, prev in zip(current_data, previous_data):
            c_memo = str(curr.get("memo", "")).strip()
            p_memo = str(prev.get("memo", "")).strip()
            if c_memo != p_memo:
                ts = curr["timestamp"]
                memo_path = os.path.join(BASE_PATH, ts, "memo.txt")
                try:
                    with open(memo_path, "w", encoding="utf-8") as f:
                        f.write(c_memo)
                except: pass
    return dash.no_update

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
        ts_to_delete = active_cell.get("row_id")
        if not ts_to_delete:
            row_idx = active_cell["row"]
            if current_data and row_idx < len(current_data):
                ts_to_delete = current_data[row_idx]["timestamp"]

        if ts_to_delete:
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
    grouped["memo"] = grouped["timestamp"].apply(get_memo)
    grouped = grouped.sort_values("timestamp")

    records = grouped.to_dict("records")
    for r in records:
        r["id"] = r["timestamp"]

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
    Input("target-ts-store", "data"),
)
def show_current_timestamp(target_ts):
    if not target_ts:
        return "テストケース詳細 (選択されていません)"
    return f"詳細表示: {target_ts}"

@app.callback(
    Output("file-name-table", "data"),
    Input("target-ts-store", "data"),
    Input("base-store", "data")
)
def update_file_table(target_ts, base_ts):
    if not target_ts: return []
    df_all = load_data()
    if df_all.empty: return []

    df_all["score"] = pd.to_numeric(df_all["score"], errors="coerce")

    if DIRECTION == "minimize":
        best_df = df_all.groupby("name")["score"].min().reset_index().rename(columns={"score": "best"})
    else:
        best_df = df_all.groupby("name")["score"].max().reset_index().rename(columns={"score": "best"})

    df = df_all[df_all["timestamp"] == target_ts].copy()

    if base_ts:
        base_df = df_all[df_all["timestamp"] == base_ts][["name", "score"]].rename(columns={"score": "base_score"})
        df = pd.merge(df, base_df, on="name", how="left")
        df["rel"] = df.apply(lambda r: r["score"] / r["base_score"] if pd.notna(r["base_score"]) and r["base_score"] != 0 else 1.0, axis=1)
    else:
        df["rel"] = 1.0

    df = pd.merge(df, best_df, on="name", how="left")
    df["time"] = pd.to_numeric(df["time"], errors="coerce")

    records = df[["name", "score", "rel", "best", "time"]].to_dict("records")
    for r in records:
        r["id"] = r["name"]

    return records

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
    State("base-store", "data")
)
def update_graph(rows, graph_type, param_x, param_y, log_scale, target_ts, table_data, base_ts):
    valid_rows = [r for r in rows if r < len(table_data)] if rows else []
    if not valid_rows or not target_ts:
        fig = px.line(title="（実行結果が選択されていません）")
        fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")
        return fig, ""

    selected_timestamps = [table_data[i]["timestamp"] for i in valid_rows]

    df_all = load_data()

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
        fig = px.line(df, x="test_id", y="score", color="timestamp", markers=True, category_orders={"timestamp": sorted_ts})
        fig.update_layout(yaxis_title="Score")

    elif graph_type == "rel":
        base_df = df_all[df_all["timestamp"] == base_ts][["test_id", "score"]].rename(columns={"score": "base_score"})
        merged = pd.merge(df, base_df, on="test_id", how="left")
        merged["relative_score"] = merged.apply(lambda r: r["score"] / r["base_score"] if pd.notna(r["base_score"]) and r["base_score"] != 0 else 1.0, axis=1)
        fig = px.line(merged, x="test_id", y="relative_score", color="timestamp", markers=True, category_orders={"timestamp": sorted_ts})
        fig.add_hline(y=1.0, line_dash="dash", line_color="#888", annotation_text=f"Base: {base_ts}")
        fig.update_layout(yaxis_title="Relative Score")

    elif graph_type == "box":
        counts = df.groupby("timestamp").size()
        df["ts_with_count"] = df["timestamp"].apply(lambda t: f"{t}<br>(n={counts.get(t,0)})")
        sorted_ts_labels = [f"{t}<br>(n={counts.get(t,0)})" for t in sorted_ts]
        fig = px.box(df, x="ts_with_count", y="score", color="timestamp")
        fig.update_xaxes(categoryorder="array", categoryarray=sorted_ts_labels)
        fig.update_layout(xaxis_title="Execution", yaxis_title="Score")

    elif graph_type.startswith("param_"):
        param_col = param_x
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

    elif graph_type in ["heatmap_abs", "heatmap_rel"]:
        meta_df = load_meta_data()
        if not meta_df.empty and param_x in meta_df.columns and param_y in meta_df.columns:
            df_hm = df_all[df_all["timestamp"] == target_ts]
            df_hm = df_hm[pd.to_numeric(df_hm["score"], errors="coerce").notna()]
            df_hm["score"] = df_hm["score"].astype(float)

            merged = pd.merge(df_hm, meta_df, on="test_id", how="left")

            if graph_type == "heatmap_rel":
                base_df = df_all[df_all["timestamp"] == base_ts][["test_id", "score"]].rename(columns={"score": "base_score"})
                merged = pd.merge(merged, base_df, on="test_id", how="left")
                merged["val"] = merged.apply(lambda r: r["score"] / r["base_score"] if pd.notna(r["base_score"]) and r["base_score"] != 0 else 1.0, axis=1)
            else:
                merged["val"] = merged["score"]

            avg_df = merged.groupby([param_y, param_x])["val"].mean().reset_index()
            pivot_df = avg_df.pivot(index=param_y, columns=param_x, values="val")
            pivot_df = pivot_df.sort_index().sort_index(axis=1).astype(float)

            if DIRECTION == "minimize":
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
                labels=dict(x=f"{param_x}", y=f"{param_y}", color="Rel Ave" if graph_type=="heatmap_rel" else "Abs Ave"),
                x=[str(x) for x in pivot_df.columns],
                y=[str(y) for y in pivot_df.index],
                aspect="auto",
                color_continuous_scale=color_scale,
                color_continuous_midpoint=zmid,
                range_color=safe_range,
                origin="lower",
                text_auto=text_fmt
            )
            fig.update_layout(xaxis_title=f"Parameter: {param_x}", yaxis_title=f"Parameter: {param_y}")
        else:
            fig = px.scatter(title="（パラメータ情報を取得できませんでした）")
            fig.update_layout(paper_bgcolor="#1e1e1e", plot_bgcolor="#1e1e1e")

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
        yaxis_type=yaxis_type
    )

    if xaxis_type:
        fig.update_layout(xaxis_type=xaxis_type)

    if graph_type == "heatmap_abs":
        summary_msg = f"ヒートマップ対象: {target_ts}"
    elif graph_type == "heatmap_rel":
        summary_msg = f"ヒートマップ対象: {target_ts} (Base: {base_ts})"
    else:
        summary_msg = f"直近に選択したケース: {target_ts}"

    return fig, summary_msg


@app.callback(
    Output("tab-content", "children"),
    Input("detail-tabs", "value"),
    Input("file-name-table", "active_cell"),
    Input("target-ts-store", "data"),
    State("file-name-table", "data"),
    State("base-store", "data"),
    State("table-data", "data") # 追加: 初期Base判定のため
)
def render_tab_content(tab, active_cell, target_ts, file_data, base_ts, table_data):
    if not target_ts:
        return html.Div("対象の実行結果が選択されていません。", style={"color": "#ccc"})

    # Baseが未指定（初期状態）の場合、全体のテーブルデータから一番古いものをBaseとみなす
    if not base_ts and table_data:
        all_timestamps = sorted(list(set([r["timestamp"] for r in table_data])))
        if all_timestamps:
            base_ts = all_timestamps[0]

    # ==== 【1】ソースコードDiffタブ (ケースの選択は不要) ====
    if tab == "tab-diff":
        target_src, target_src_name = load_source_code(target_ts)
        base_src, base_src_name = load_source_code(base_ts) if base_ts else ("", "")

        if not base_ts:
            diff_text = "(Baseとなる比較対象が見つかりません)"
            src_label = target_src_name
        else:
            diff_lines = list(difflib.unified_diff(
                base_src.splitlines(),
                target_src.splitlines(),
                fromfile=f"Base ({base_ts}/{base_src_name})",
                tofile=f"Target ({target_ts}/{target_src_name})",
                lineterm=""
            ))
            
            diff_text = "\n".join(diff_lines)
            if not diff_text.strip():
                diff_text = "差分はありません (同一コードです)"
            src_label = target_src_name or base_src_name

        return html.Div(style={"display": "flex", "flexDirection": "column", "gap": "10px", "height": "100%"}, children=[
            html.H4(f"ソースコード 差分 ({src_label}) [Base vs Target]", style={"margin": "0", "color": "#ccc"}),
            html.Div(className="code-container", style={"flex": "1"}, children=[
                dcc.Clipboard(content=diff_text, className="clipboard-btn"),
                dcc.Textarea(value=diff_text, className="code-textarea", readOnly=True)
            ])
        ])

    # ==== 【2】標準出力・ビジュアライザタブ (左のリストからケースの選択が必須) ====
    if not active_cell or not file_data:
        return html.Div("ファイルが選択されていません。左の表からCaseを選択してください。", style={"color": "#ccc"})

    filename = active_cell.get("row_id")
    if not filename:
        if active_cell["row"] >= len(file_data):
            return html.Div("ファイルが見つかりません。", style={"color": "#ccc"})
        filename = file_data[active_cell["row"]]["name"]

    timestamp = target_ts

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
