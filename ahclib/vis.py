import os
import pandas as pd
import plotly.express as px
from datetime import datetime
from dash import Dash, dcc, html, dash_table, ctx
from dash.dependencies import Input, Output, State

BASE_PATH = "ahclib_results/all_tests"
FILE_NAME = "result.csv"


def format_timestamp(ts):
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M").strftime("%Y/%m/%d %H:%M")
    except:
        return ts


def load_data():
    data = []
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
        return pd.DataFrame(
            columns=[
                "filename",
                "score",
                "state",
                "time",
                "timestamp",
                "name",
                "test_id",
            ]
        )
    df_all = pd.concat(data, ignore_index=True)
    return df_all


def load_err_out_files(timestamp):
    base_dir = os.path.join(BASE_PATH, timestamp)
    err_dir = os.path.join(base_dir, "err")
    out_dir = os.path.join(base_dir, "out")

    err_files, out_files = {}, {}
    if os.path.isdir(err_dir):
        for fname in os.listdir(err_dir):
            with open(
                os.path.join(err_dir, fname), encoding="utf-8", errors="ignore"
            ) as f:
                err_files[fname] = f.read()
    if os.path.isdir(out_dir):
        for fname in os.listdir(out_dir):
            with open(
                os.path.join(out_dir, fname), encoding="utf-8", errors="ignore"
            ) as f:
                out_files[fname] = f.read()
    return err_files, out_files


app = Dash(__name__)

app.layout = html.Div(
    [
        dcc.Store(id="err-content-store"),
        dcc.Store(id="out-content-store"),
        html.H1("AHC Result Dashboard", style={"textAlign": "center"}),
        html.Div(
            [
                html.H3("実行結果一覧"),
                dash_table.DataTable(
                    id="timestamp-table",
                    columns=[
                        {"name": "time", "id": "formatted"},
                        {
                            "name": "average",
                            "id": "average_score",
                            "type": "numeric",
                            "format": {"specifier": ".2f"},
                        },
                    ],
                    style_table={"maxHeight": "300px", "overflowY": "scroll"},
                    row_selectable="multi",
                    selected_rows=[],
                    style_cell={
                        "textAlign": "left",
                        "userSelect": "text",
                    },
                    style_header={"fontWeight": "bold"},
                ),
                html.Div(
                    [
                        html.Button("🔄 Reload", id="reload-button", n_clicks=0),
                        html.Button("🆕 直近3件を選択", id="select-recent", n_clicks=0),
                        html.Button("✅ すべて選択", id="select-all", n_clicks=0),
                        html.Button("❌ 選択解除", id="clear-selection", n_clicks=0),
                    ],
                    style={"marginTop": "10px", "marginBottom": "10px"},
                ),
                dcc.Store(id="table-data", data=[]),
            ],
            style={"padding": "10px"},
        ),
        html.Div(
            [
                dcc.Graph(id="score-comparison-graph"),
                html.Div(
                    id="summary-text", style={"marginTop": "10px", "fontWeight": "bold"}
                ),
            ],
            style={"padding": "10px"},
        ),
        html.H3("各テストケースの出力表示"),
        html.Div(
            id="current-timestamp-display",
            style={"fontWeight": "bold", "marginBottom": "8px"},
        ),
        html.Div(
            [
                dash_table.DataTable(
                    id="file-name-table",
                    columns=[
                        {"name": "name", "id": "name"},
                        {"name": "score", "id": "score"},
                        {"name": "time", "id": "time"},
                    ],
                    sort_action="native",
                    style_cell={
                        "textAlign": "left",
                        "userSelect": "text",
                        "fontFamily": "monospace",
                    },
                    style_table={
                        "maxHeight": "600px",
                        "overflowY": "scroll",
                        "minWidth": "200px",
                    },
                    cell_selectable=True,
                    style_as_list_view=True,
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Div(
                                    [html.H4(id="err-title")],
                                    style={
                                        "display": "flex",
                                        "alignItems": "center",
                                        "gap": "10px",
                                    },
                                ),
                                dcc.Markdown(id="err-output", className="code-block"),
                            ]
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [html.H4(id="out-title")],
                                    style={
                                        "display": "flex",
                                        "alignItems": "center",
                                        "gap": "10px",
                                    },
                                ),
                                dcc.Markdown(id="out-output", className="code-block"),
                            ]
                        ),
                    ],
                    style={
                        "flex": "3",
                        "padding": "0 20px",
                        "border": "1px solid #ccc",
                        "borderRadius": "5px",
                        "marginLeft": "20px",
                        "maxHeight": "600px",
                        "overflowY": "auto",
                    },
                ),
            ],
            style={"display": "flex", "width": "100%", "padding": "10px"},
        ),
    ]
)


@app.callback(
    Output("current-timestamp-display", "children"),
    Input("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def show_current_timestamp(selected_rows, table_data):
    if not selected_rows or not table_data:
        return "実行結果が選択されていません。"
    latest_ts = table_data[selected_rows[-1]]["timestamp"]
    return f"現在表示中の実行結果: {latest_ts}"


@app.callback(
    Output("timestamp-table", "data"),
    Output("table-data", "data"),
    Input("reload-button", "n_clicks"),
)
def update_table(n):
    df = load_data()
    if df.empty:
        return [], []
    grouped = df.groupby("timestamp").agg(average_score=("score", "mean")).reset_index()
    grouped["formatted"] = grouped["timestamp"].apply(format_timestamp)
    grouped = grouped.sort_values("timestamp")
    return grouped.to_dict("records"), grouped.to_dict("records")


@app.callback(
    Output("timestamp-table", "selected_rows"),
    Input("select-recent", "n_clicks"),
    Input("select-all", "n_clicks"),
    Input("clear-selection", "n_clicks"),
    Input("reload-button", "n_clicks"),
    State("table-data", "data"),
    State("timestamp-table", "selected_rows"),
)
def select_timestamp(n_recent, n_all, n_clear, n_reload, data, prev):
    if not data:
        return []
    triggered = ctx.triggered_id
    if triggered == "select-recent":
        return list(range(max(0, len(data) - 3), len(data)))
    if triggered == "select-all":
        return list(range(len(data)))
    if triggered == "clear-selection":
        return []
    if triggered == "reload-button":
        if prev:
            prev_ts = {data[i]["timestamp"] for i in prev if i < len(data)}
            new_selection = [
                i
                for i, row in enumerate(data)
                if row["timestamp"] in prev_ts
                or row["timestamp"] > max(prev_ts, default="")
            ]
            return sorted(list(set(new_selection)))
        return list(range(max(0, len(data) - 3), len(data)))
    return prev or []


@app.callback(
    Output("score-comparison-graph", "figure"),
    Output("summary-text", "children"),
    Input("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def update_graph(rows, table_data):
    if not rows:
        return (
            px.line(title="（実行結果が選択されていません）"),
            "実行結果が選択されていません。",
        )
    selected_timestamps = [table_data[i]["timestamp"] for i in rows]
    df_all = load_data()
    df = df_all[df_all["timestamp"].isin(selected_timestamps)]
    df = df[pd.to_numeric(df["score"], errors="coerce").notna()]
    if not df.empty:
        df["score"] = df["score"].astype(float)
    df_graph = df
    if df_graph.empty:
        fig = px.line(title="（表示するデータがありません）")
    else:
        fig = px.line(
            df_graph,
            x="test_id",
            y="score",
            color="timestamp",
            markers=True,
            category_orders={"timestamp": sorted(selected_timestamps)},
        )
    fig.update_layout(
        xaxis_title="TestCase", yaxis_title="Score", hovermode="x unified"
    )
    summary_msg = f"選択中：{len(selected_timestamps)} 件"
    return fig, summary_msg


@app.callback(
    Output("file-name-table", "data"),
    Input("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def update_file_table(selected_rows, table_data):
    if not selected_rows or not table_data:
        return []
    timestamp = table_data[selected_rows[-1]]["timestamp"]
    df = load_data()
    df = df[df["timestamp"] == timestamp]
    return df[["name", "score", "time"]].to_dict("records")


@app.callback(
    Output("err-output", "children"),
    Output("out-output", "children"),
    Output("err-title", "children"),
    Output("out-title", "children"),
    Output("err-content-store", "data"),
    Output("out-content-store", "data"),
    Input("file-name-table", "active_cell"),
    State("file-name-table", "data"),
    State("timestamp-table", "selected_rows"),
    State("table-data", "data"),
)
def display_output(active_cell, file_data, ts_rows, ts_data):
    if not active_cell or not file_data or not ts_rows or not ts_data:
        no_selection_msg = "```\nファイルが選択されていません。\n```"
        return no_selection_msg, no_selection_msg, "標準エラー出力", "標準出力", "", ""

    filename = file_data[active_cell["row"]]["name"]
    timestamp = ts_data[ts_rows[-1]]["timestamp"]
    err_files, out_files = load_err_out_files(timestamp)

    err_content_raw = err_files.get(filename, "(errファイルなし)")
    out_content_raw = out_files.get(filename, "(outファイルなし)")

    err_content_md = f"```text\n{err_content_raw}\n```"
    out_content_md = f"```text\n{out_content_raw}\n```"

    err_title = f"標準エラー出力 (err)"
    out_title = f"標準出力 (out)"

    return (
        err_content_md,
        out_content_md,
        err_title,
        out_title,
        err_content_raw,
        out_content_raw,
    )


if __name__ == "__main__":
    app.run(debug=False)
