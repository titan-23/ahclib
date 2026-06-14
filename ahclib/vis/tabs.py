import os
import json
import difflib

from dash import dcc, html

from . import config


def render_tab_content(
    store, tab, active_cell, target_ts, file_data, base_ts, table_data
):
    if not target_ts:
        return html.Div("対象の実行結果が選択されていません。", style={"color": "#ccc"})

    if not base_ts and table_data:
        all_timestamps = sorted(list(set([r["timestamp"] for r in table_data])))
        if all_timestamps:
            base_ts = all_timestamps[0]

    # Diff はケース選択を必要としないので先に処理する
    if tab == "tab-diff":
        return _render_diff_tab(store, target_ts, base_ts)

    if not active_cell or not file_data:
        return html.Div(
            "ファイルが選択されていません。左の表からCaseを選択してください。",
            style={"color": "#ccc"},
        )

    filename = active_cell.get("row_id")
    if not filename:
        if active_cell["row"] >= len(file_data):
            return html.Div("ファイルが見つかりません。", style={"color": "#ccc"})
        filename = file_data[active_cell["row"]]["name"]

    timestamp = target_ts

    if tab == "tab-text":
        return _render_text_tab(store, timestamp, filename)

    elif tab == "tab-vis":
        return _render_vis_tab(store, timestamp, filename)


def _render_diff_tab(store, target_ts, base_ts):
    target_src, target_src_name = store.source(target_ts)
    base_src, base_src_name = store.source(base_ts) if base_ts else ("", "")

    if not base_ts:
        diff_text = "(Baseとなる比較対象が見つかりません)"
        src_label = target_src_name
    else:
        diff_lines = list(
            difflib.unified_diff(
                base_src.splitlines(),
                target_src.splitlines(),
                fromfile=f"Base ({base_ts}/{base_src_name})",
                tofile=f"Target ({target_ts}/{target_src_name})",
                lineterm="",
            )
        )

        diff_text = "\n".join(diff_lines)
        if not diff_text.strip():
            diff_text = "差分はありません (同一コードです)"
        src_label = target_src_name or base_src_name

    return html.Div(
        style={
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "height": "100%",
        },
        children=[
            html.H4(
                f"ソースコード 差分 ({src_label}) [Base vs Target]",
                style={"margin": "0", "color": "#ccc"},
            ),
            html.Div(
                className="code-container",
                style={"flex": "1"},
                children=[
                    dcc.Clipboard(content=diff_text, className="clipboard-btn"),
                    html.Pre(
                        children=_colorize_diff(diff_text),
                        className="code-textarea",
                        style={"margin": "0", "overflow": "auto"},
                    ),
                ],
            ),
        ],
    )


def _colorize_diff(diff_text):
    """unified diff の各行を追加・削除・ヘッダで色分けした span のリストにする"""
    lines = []
    for line in diff_text.split("\n"):
        if line.startswith("+++") or line.startswith("---"):
            color = "#888"
        elif line.startswith("@@"):
            color = "#29b6f6"
        elif line.startswith("+"):
            color = "#81c784"
        elif line.startswith("-"):
            color = "#e57373"
        else:
            color = "#e0e0e0"
        lines.append(html.Span(line + "\n", style={"color": color}))
    return lines


def _render_text_tab(store, timestamp, filename):
    err_text, out_text = store.out_err(timestamp, filename)

    return html.Div(
        style={
            "display": "flex",
            "flexDirection": "row",
            "gap": "20px",
            "height": "100%",
        },
        children=[
            html.Div(
                style={
                    "flex": "1",
                    "display": "flex",
                    "flexDirection": "column",
                    "minWidth": "0",
                    "minHeight": "0",
                },
                children=[
                    html.H4(
                        "標準エラー出力 (err)",
                        style={"margin": "0 0 10px 0", "color": "#ccc"},
                    ),
                    html.Div(
                        className="code-container",
                        style={"flex": "1"},
                        children=[
                            dcc.Clipboard(content=err_text, className="clipboard-btn"),
                            dcc.Textarea(
                                value=err_text,
                                className="code-textarea",
                                readOnly=True,
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                style={
                    "flex": "1",
                    "display": "flex",
                    "flexDirection": "column",
                    "minWidth": "0",
                    "minHeight": "0",
                },
                children=[
                    html.H4(
                        "標準出力 (out)",
                        style={"margin": "0 0 10px 0", "color": "#ccc"},
                    ),
                    html.Div(
                        className="code-container",
                        style={"flex": "1"},
                        children=[
                            dcc.Clipboard(content=out_text, className="clipboard-btn"),
                            dcc.Textarea(
                                value=out_text,
                                className="code-textarea",
                                readOnly=True,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _render_vis_tab(store, timestamp, filename):
    in_text = store.in_file(filename)
    _, out_text = store.out_err(timestamp, filename)
    if out_text == "(outファイルなし)":
        out_text = ""

    vis_html = config.vis_html_path()
    if os.path.exists(vis_html):
        with open(vis_html, "r", encoding="utf-8") as f:
            html_template = f.read()

        js_data_block = f"<script>\nconst INPUT_DATA = {json.dumps(in_text)};\nconst OUTPUT_DATA = {json.dumps(out_text)};\n</script>"
        src_doc = html_template.replace("</body>", f"{js_data_block}\n</body>")

        return html.Iframe(
            srcDoc=src_doc,
            style={
                "width": "100%",
                "height": "100%",
                "border": "none",
                "backgroundColor": "#fff",
            },
        )
    else:
        return html.Div(
            "ビジュアライザのHTMLファイルが見つかりません。",
            style={"color": "#e57373", "fontWeight": "bold", "padding": "20px"},
        )
