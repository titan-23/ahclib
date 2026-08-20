import difflib
import re
from typing import Any, Optional
from urllib.parse import urlencode

from dash import dcc, html
from dash.development.base_component import Component

from .data import ResultSnapshot, ResultStore

TEXT_PREVIEW_LIMIT = 200_000
TEXT_PREVIEW_HEAD = 140_000
TEXT_PREVIEW_TAIL = 40_000
MAX_HIGHLIGHTED_MATCHES = 500


def preview_text(content: str, full: bool = False) -> tuple[str, int]:
    """長いテキストを先頭と末尾のプレビューへ縮める"""
    if full or len(content) <= TEXT_PREVIEW_LIMIT:
        return content, 0

    omitted = len(content) - TEXT_PREVIEW_HEAD - TEXT_PREVIEW_TAIL
    marker = f"\n\n... {omitted:,} 文字省略 ...\n\n"
    return content[:TEXT_PREVIEW_HEAD] + marker + content[-TEXT_PREVIEW_TAIL:], omitted


def _match_count(content: str, search: Optional[str]) -> int:
    if not search:
        return 0
    pattern = re.compile(re.escape(search), flags=re.IGNORECASE)
    return sum(1 for _match in pattern.finditer(content))


def _highlighted_text(
    content: str,
    search: Optional[str],
) -> list[Any]:
    if not search:
        return [content]

    pattern = re.compile(re.escape(search), flags=re.IGNORECASE)
    parts: list[Any] = []
    last = 0
    for index, match in enumerate(pattern.finditer(content)):
        if index >= MAX_HIGHLIGHTED_MATCHES:
            break
        if match.start() > last:
            parts.append(content[last : match.start()])
        parts.append(
            html.Mark(
                match.group(),
                style={"backgroundColor": "#ffca28", "color": "#111"},
            )
        )
        last = match.end()
    parts.append(content[last:])
    return parts


def _highlighted_diff(content: str, search: Optional[str]) -> list[Component]:
    lines = []
    for line in content.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped.startswith(("+++", "---")):
            color = "#888"
        elif stripped.startswith("@@"):
            color = "#29b6f6"
        elif stripped.startswith("+"):
            color = "#81c784"
        elif stripped.startswith("-"):
            color = "#e57373"
        else:
            color = "#e0e0e0"
        lines.append(
            html.Span(
                _highlighted_text(line, search),
                style={"color": color},
            )
        )
    return lines


def _code_panel(
    title: str,
    content: str,
    search: Optional[str],
    wrap: bool,
    full: bool,
    colorize_diff: bool = False,
) -> tuple[Component, int, int]:
    """見出しとコピー付きの読み取り専用コードパネルを返す"""
    shown, omitted = preview_text(content, full=full)
    matches = _match_count(content, search)
    white_space = "pre-wrap" if wrap else "pre"
    note = f"プレビュー表示中 省略 {omitted:,} 文字" if omitted else ""
    return (
        html.Div(
            style={
                "display": "flex",
                "flexDirection": "column",
                "gap": "8px",
                "height": "100%",
                "minWidth": "0",
                "minHeight": "0",
            },
            children=[
                html.Div(
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "justifyContent": "space-between",
                        "gap": "8px",
                    },
                    children=[
                        html.H4(title, style={"margin": "0", "color": "#ccc"}),
                        html.Span(note, style={"fontSize": "11px", "color": "#ffca28"}),
                    ],
                ),
                html.Div(
                    className="code-container",
                    style={"flex": "1", "minHeight": "0"},
                    children=[
                        dcc.Clipboard(content=shown, className="clipboard-btn"),
                        html.Pre(
                            (_highlighted_diff(shown, search) if colorize_diff else _highlighted_text(shown, search)),
                            className="code-textarea",
                            style={
                                "margin": "0",
                                "overflow": "auto",
                                "whiteSpace": white_space,
                                "wordBreak": "break-word" if wrap else "normal",
                            },
                        ),
                    ],
                ),
            ],
        ),
        matches,
        omitted,
    )


def _result_text(
    matches: int,
    omitted: int,
    search: Optional[str],
) -> str:
    parts = []
    if search:
        parts.append(f"検索一致 {matches:,} 件")
    if omitted:
        parts.append(f"省略 {omitted:,} 文字")
    return " / ".join(parts)


def render_tab_content(
    store: ResultStore,
    snapshot: ResultSnapshot,
    tab: str,
    selected_case: Optional[dict[str, Any]],
    target_ts: Optional[str],
    base_ts: Optional[str],
    search: Optional[str] = None,
    view_options: Optional[list[str]] = None,
) -> tuple[Optional[Component], str]:
    if not target_ts:
        return (
            html.Div("対象の実行結果が選択されていません", style={"color": "#ccc"}),
            "",
        )

    timestamps = sorted(snapshot.results["timestamp"].dropna().astype(str).unique())
    if target_ts not in timestamps:
        return html.Div("対象の実行結果が見つかりません", style={"color": "#ccc"}), ""
    if base_ts not in timestamps:
        base_ts = timestamps[0] if timestamps else None

    options = set(view_options or [])
    wrap = "wrap" in options
    full = "full" in options

    if tab == "tab-src":
        return _render_src_tab(store, target_ts, search, wrap, full)

    if tab == "tab-diff":
        return _render_diff_tab(store, target_ts, base_ts, search, wrap, full)

    if not selected_case:
        return (
            html.Div(
                "ファイルが選択されていません 左の表から Case を選択してください",
                style={"color": "#ccc"},
            ),
            "",
        )

    case_id = str(selected_case.get("id") or selected_case.get("case_id") or "")
    target_case = snapshot.case(target_ts, case_id) if case_id else None
    if not target_case:
        return html.Div("ファイルが見つかりません", style={"color": "#ccc"}), ""
    filename = target_case.get("name")
    input_filename = target_case.get("filename", filename)
    if not filename:
        return html.Div("ファイルが見つかりません", style={"color": "#ccc"}), ""

    if tab == "tab-text":
        base_case = snapshot.case(base_ts, case_id) if base_ts else None
        return _render_text_tab(
            store,
            target_ts,
            str(filename),
            base_ts,
            base_case,
            search,
            wrap,
            full,
        )

    if tab == "tab-in":
        return _render_in_tab(
            store,
            str(input_filename),
            str(filename),
            search,
            wrap,
            full,
        )

    if tab == "tab-vis":
        if not store.visualizer_template():
            return (
                html.Div(
                    "ビジュアライザの HTML ファイルが見つかりません",
                    style={
                        "color": "#e57373",
                        "fontWeight": "bold",
                        "padding": "20px",
                    },
                ),
                "",
            )
        return _render_vis_tab(target_ts, case_id), ""

    return None, ""


def _render_src_tab(
    store: ResultStore,
    target_ts: str,
    search: Optional[str],
    wrap: bool,
    full: bool,
) -> tuple[Component, str]:
    source_code, source_name = store.source(target_ts)
    panel, matches, omitted = _code_panel(
        f"ソースコード ({source_name})",
        source_code,
        search,
        wrap,
        full,
    )
    return panel, _result_text(matches, omitted, search)


def _render_in_tab(
    store: ResultStore,
    input_filename: str,
    display_filename: str,
    search: Optional[str],
    wrap: bool,
    full: bool,
) -> tuple[Component, str]:
    input_text = store.in_file(input_filename) or "(入力ファイルが見つかりません)"
    panel, matches, omitted = _code_panel(
        f"入力 ({display_filename})",
        input_text,
        search,
        wrap,
        full,
    )
    return panel, _result_text(matches, omitted, search)


def _render_diff_tab(
    store: ResultStore,
    target_ts: str,
    base_ts: Optional[str],
    search: Optional[str],
    wrap: bool,
    full: bool,
) -> tuple[Component, str]:
    target_source, target_source_name = store.source(target_ts)
    base_source, base_source_name = store.source(base_ts) if base_ts else ("", "")

    if not base_ts:
        diff_text = "(Base となる比較対象が見つかりません)"
        source_label = target_source_name
    else:
        diff_lines = difflib.unified_diff(
            base_source.splitlines(),
            target_source.splitlines(),
            fromfile=f"Base ({base_ts}/{base_source_name})",
            tofile=f"Target ({target_ts}/{target_source_name})",
            lineterm="",
        )
        diff_text = "\n".join(diff_lines) or "差分はありません (同一コードです)"
        source_label = target_source_name or base_source_name

    panel, matches, omitted = _code_panel(
        f"ソースコード差分 ({source_label}) [Base vs Target]",
        diff_text,
        search,
        wrap,
        full,
        colorize_diff=True,
    )
    return panel, _result_text(matches, omitted, search)


def _render_text_tab(
    store: ResultStore,
    timestamp: str,
    filename: str,
    base_ts: Optional[str],
    base_case: Optional[dict[str, Any]],
    search: Optional[str],
    wrap: bool,
    full: bool,
) -> tuple[Component, str]:
    target_error, target_output = store.out_err(timestamp, filename)
    panels = []
    total_matches = 0
    total_omitted = 0

    for title, content in [
        (f"Target err ({timestamp})", target_error),
        (f"Target out ({timestamp})", target_output),
    ]:
        panel, matches, omitted = _code_panel(title, content, search, wrap, full)
        panels.append(panel)
        total_matches += matches
        total_omitted += omitted

    if base_ts and base_case:
        base_name = str(base_case.get("name") or filename)
        base_error, base_output = store.out_err(base_ts, base_name)
        for title, content in [
            (f"Base err ({base_ts})", base_error),
            (f"Base out ({base_ts})", base_output),
        ]:
            panel, matches, omitted = _code_panel(title, content, search, wrap, full)
            panels.append(panel)
            total_matches += matches
            total_omitted += omitted

    component = html.Div(
        className="result-text-grid",
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
            "gridAutoRows": "minmax(260px, 1fr)",
            "gap": "16px",
            "height": "100%",
        },
        children=panels,
    )
    return component, _result_text(total_matches, total_omitted, search)


def _render_vis_tab(timestamp: str, case_id: str) -> Component:
    query = urlencode({"timestamp": timestamp, "case_id": case_id})
    return html.Iframe(
        src=f"/_ahclib_visualizer?{query}",
        sandbox="allow-scripts",
        style={
            "width": "100%",
            "height": "100%",
            "border": "none",
            "backgroundColor": "#fff",
        },
    )
