import difflib
import json
import os
from typing import Any, Optional

from dash import dcc, html
from dash.development.base_component import Component

from . import config
from .data import ResultStore


def render_tab_content(
    store: ResultStore,
    tab: str,
    active_cell: Optional[dict[str, Any]],
    target_ts: Optional[str],
    file_data: list[dict[str, Any]],
    base_ts: Optional[str],
    table_data: list[dict[str, Any]],
) -> Optional[Component]:
    if not target_ts:
        return html.Div("対象の実行結果が選択されていません。", style={"color": "#ccc"})

    if not base_ts and table_data:
        all_timestamps = sorted(list({row["timestamp"] for row in table_data}))
        if all_timestamps:
            base_ts = all_timestamps[0]

    # ソースコードと差分はケース選択を必要としないため先に処理する
    if tab == "tab-src":
        return _render_src_tab(store, target_ts)

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

    elif tab == "tab-in":
        return _render_in_tab(store, filename)

    elif tab == "tab-vis":
        return _render_vis_tab(store, timestamp, filename)


def _code_panel(title: str, content: str) -> Component:
    """見出しとコピー付きの読み取り専用コードパネルを返す"""
    return html.Div(
        style={
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "height": "100%",
        },
        children=[
            html.H4(title, style={"margin": "0", "color": "#ccc"}),
            html.Div(
                className="code-container",
                style={"flex": "1"},
                children=[
                    dcc.Clipboard(content=content, className="clipboard-btn"),
                    dcc.Textarea(
                        value=content, className="code-textarea", readOnly=True
                    ),
                ],
            ),
        ],
    )


def _render_src_tab(store: ResultStore, target_ts: str) -> Component:
    source_code, source_name = store.source(target_ts)
    return _code_panel(f"ソースコード ({source_name})", source_code)


def _render_in_tab(store: ResultStore, filename: str) -> Component:
    input_text = store.in_file(filename)
    if not input_text:
        input_text = "(入力ファイルが見つかりません)"
    return _code_panel(f"入力 ({filename})", input_text)


def _render_diff_tab(
    store: ResultStore,
    target_ts: str,
    base_ts: Optional[str],
) -> Component:
    target_source, target_source_name = store.source(target_ts)
    base_source, base_source_name = store.source(base_ts) if base_ts else ("", "")

    if not base_ts:
        diff_text = "(Baseとなる比較対象が見つかりません)"
        source_label = target_source_name
    else:
        diff_lines = list(
            difflib.unified_diff(
                base_source.splitlines(),
                target_source.splitlines(),
                fromfile=f"Base ({base_ts}/{base_source_name})",
                tofile=f"Target ({target_ts}/{target_source_name})",
                lineterm="",
            )
        )

        diff_text = "\n".join(diff_lines)
        if not diff_text.strip():
            diff_text = "差分はありません (同一コードです)"
        source_label = target_source_name or base_source_name

    return html.Div(
        style={
            "display": "flex",
            "flexDirection": "column",
            "gap": "10px",
            "height": "100%",
        },
        children=[
            html.H4(
                f"ソースコード 差分 ({source_label}) [Base vs Target]",
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


def _colorize_diff(diff_text: str) -> list[Component]:
    """unified diff の各行を種類に応じて色分けする"""
    styled_lines = []
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
        styled_lines.append(html.Span(line + "\n", style={"color": color}))
    return styled_lines


def _render_text_tab(
    store: ResultStore,
    timestamp: str,
    filename: str,
) -> Component:
    error_text, output_text = store.out_err(timestamp, filename)

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
                            dcc.Clipboard(
                                content=error_text,
                                className="clipboard-btn",
                            ),
                            dcc.Textarea(
                                value=error_text,
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
                            dcc.Clipboard(
                                content=output_text,
                                className="clipboard-btn",
                            ),
                            dcc.Textarea(
                                value=output_text,
                                className="code-textarea",
                                readOnly=True,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _render_vis_tab(
    store: ResultStore,
    timestamp: str,
    filename: str,
) -> Component:
    input_text = store.in_file(filename)
    _, output_text = store.out_err(timestamp, filename)
    if output_text == "(outファイルなし)":
        output_text = ""

    visualizer_path = config.vis_html_path()
    if os.path.exists(visualizer_path):
        with open(visualizer_path, "r", encoding="utf-8") as visualizer_file:
            html_template = visualizer_file.read()

        data_script = (
            f"<script>\nconst INPUT_DATA = {json.dumps(input_text)};\n"
            f"const OUTPUT_DATA = {json.dumps(output_text)};\n</script>"
        )
        document = html_template.replace("</body>", f"{data_script}\n</body>")

        return html.Iframe(
            srcDoc=document,
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
