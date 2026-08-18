import dash_ag_grid as dag
from dash import dcc, html
from dash.development.base_component import Component

from . import config


def _graph_type_radio() -> Component:
    options = [
        ("絶対スコア", "abs"),
        ("相対スコア", "rel"),
        ("箱ひげ図", "box"),
        ("相関(散布図)", "param_scatter"),
        ("相関(Box)", "param_box"),
        ("相関(平均)", "param_line"),
        ("HM(絶対)", "heatmap_abs"),
        ("HM(相対)", "heatmap_rel"),
        ("CV(Box)", "difficulty_box"),
        ("CV(HM)", "difficulty_heatmap"),
        ("スコア×時間", "score_time"),
        ("回帰Δ", "regression"),
    ]
    return dcc.RadioItems(
        id="graph-type",
        options=[
            {
                "label": html.Span(label, style={"paddingLeft": "4px"}),
                "value": value,
            }
            for label, value in options
        ],
        value="abs",
        inline=True,
        persistence=True,
        persistence_type="session",
        style={"display": "flex", "gap": "12px"},
        labelStyle={
            "cursor": "pointer",
            "color": "#e0e0e0",
            "display": "flex",
            "alignItems": "center",
            "fontSize": "13px",
        },
    )


def _build_sidebar(direction: str, read_only: bool) -> Component:
    return html.Div(
        id="sidebar-container",
        className="sidebar-base sidebar-pinned",
        children=[
            html.Div(
                className="sidebar-content",
                children=[
                    html.Div(
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "marginBottom": "15px",
                            "justifyContent": "space-between",
                        },
                        children=[
                            html.H2(
                                "AHC Dashboard",
                                style={"margin": "0", "fontSize": "20px"},
                            ),
                            html.Button(
                                "◀",
                                id="pin-btn",
                                className="btn-pin",
                                title="サイドバーの固定を解除する",
                            ),
                        ],
                    ),
                    html.Div(
                        style={
                            "display": "flex",
                            "flexWrap": "wrap",
                            "gap": "8px",
                            "marginBottom": "10px",
                        },
                        children=[
                            html.Button(
                                "🔄 更新",
                                id="reload-button",
                                className="btn",
                                n_clicks=0,
                            ),
                            html.Button(
                                "🆕 直近を追加",
                                id="add-latest",
                                className="btn",
                                n_clicks=0,
                            ),
                            html.Button(
                                "◀ 直前を Base",
                                id="previous-base",
                                className="btn",
                                n_clicks=0,
                            ),
                            dcc.Checklist(
                                id="base-mode-check",
                                options=[
                                    {
                                        "label": " Base を Target の直前へ追従",
                                        "value": "previous",
                                    }
                                ],
                                value=[],
                                persistence=True,
                                persistence_type="session",
                                style={"fontSize": "12px", "alignSelf": "center"},
                            ),
                            html.Button(
                                "✅ 全選択",
                                id="select-all",
                                className="btn",
                                n_clicks=0,
                            ),
                            html.Button(
                                "❌ 解除",
                                id="clear-selection",
                                className="btn",
                                n_clicks=0,
                            ),
                            dcc.Checklist(
                                id="auto-refresh-check",
                                options=[
                                    {
                                        "label": html.Span(
                                            " 自動更新",
                                            style={
                                                "paddingLeft": "4px",
                                                "color": "#e0e0e0",
                                            },
                                        ),
                                        "value": "on",
                                    }
                                ],
                                value=[],
                                labelStyle={
                                    "cursor": "pointer",
                                    "display": "flex",
                                    "alignItems": "center",
                                },
                                style={"fontSize": "12px", "alignSelf": "center"},
                            ),
                        ],
                    ),
                    dcc.Interval(
                        id="auto-refresh-interval",
                        interval=5000,
                        disabled=True,
                    ),
                    html.Div(
                        style={"flex": "1", "overflowY": "auto"},
                        children=[
                            dag.AgGrid(
                                id="timestamp-table",
                                columnDefs=config.run_column_defs(
                                    direction,
                                    read_only=read_only,
                                ),
                                rowData=[],
                                getRowId="params.data.id",
                                selectedRows=[],
                                defaultColDef={
                                    "sortable": True,
                                    "resizable": True,
                                    "filter": True,
                                    "minWidth": 80,
                                },
                                dashGridOptions={
                                    "theme": config.GRID_THEME,
                                    "animateRows": False,
                                    "rowSelection": {
                                        "mode": "multiRow",
                                        "enableClickSelection": True,
                                        "checkboxes": True,
                                        "headerCheckbox": False,
                                    },
                                    "selectionColumnDef": {
                                        "width": 44,
                                        "pinned": "left",
                                    },
                                },
                                style={"width": "100%", "height": "100%"},
                            )
                        ],
                    ),
                    html.Div(
                        (
                            "読み取り専用モード"
                            if read_only
                            else "※ Memo 列と Tag 列は編集後に自動保存されます"
                        ),
                        style={
                            "fontSize": "11px",
                            "color": "#888",
                            "marginTop": "5px",
                        },
                    ),
                ],
            )
        ],
    )


def _build_main(direction: str, read_only: bool) -> Component:
    return html.Div(
        className="main-content",
        children=[
            html.Div(
                id="graph-card",
                className="card",
                children=[
                    html.Div(
                        style={
                            "display": "flex",
                            "justifyContent": "space-between",
                            "alignItems": "center",
                            "marginBottom": "10px",
                            "flexWrap": "wrap",
                            "gap": "10px",
                        },
                        children=[
                            html.Div(
                                id="summary-text",
                                style={
                                    "fontWeight": "bold",
                                    "color": "#ccc",
                                    "minWidth": "150px",
                                },
                            ),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "15px",
                                    "flexWrap": "wrap",
                                },
                                children=[
                                    _graph_type_radio(),
                                    html.Div(
                                        id="param-selector-container",
                                        style={
                                            "display": "none",
                                            "alignItems": "center",
                                            "gap": "5px",
                                        },
                                        children=[
                                            html.Div(
                                                id="param-y-wrapper",
                                                style={
                                                    "display": "none",
                                                    "alignItems": "center",
                                                    "gap": "5px",
                                                },
                                                children=[
                                                    dcc.Dropdown(
                                                        id="param-selector-y",
                                                        options=[],
                                                        clearable=False,
                                                        persistence=True,
                                                        persistence_type="session",
                                                        style={
                                                            "width": "80px",
                                                            "color": "#333",
                                                        },
                                                        className="dash-dropdown",
                                                    ),
                                                    html.Span(
                                                        "×",
                                                        style={
                                                            "color": "#aaa",
                                                            "paddingBottom": "2px",
                                                        },
                                                    ),
                                                ],
                                            ),
                                            dcc.Dropdown(
                                                id="param-selector",
                                                options=[],
                                                clearable=False,
                                                persistence=True,
                                                persistence_type="session",
                                                style={
                                                    "width": "80px",
                                                    "color": "#333",
                                                },
                                                className="dash-dropdown",
                                            ),
                                        ],
                                    ),
                                    dcc.Checklist(
                                        id="log-scale-check",
                                        options=[
                                            {
                                                "label": html.Span(
                                                    " Y 軸を Log スケール",
                                                    style={
                                                        "paddingLeft": "4px",
                                                        "color": "#e0e0e0",
                                                    },
                                                ),
                                                "value": "log",
                                            }
                                        ],
                                        value=[],
                                        persistence=True,
                                        persistence_type="session",
                                        labelStyle={
                                            "cursor": "pointer",
                                            "display": "flex",
                                            "alignItems": "center",
                                        },
                                        style={"fontSize": "13px"},
                                    ),
                                    html.Button(
                                        "Zoom reset",
                                        id="graph-reset",
                                        className="btn",
                                        n_clicks=0,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    dcc.Graph(id="score-comparison-graph", style={"height": "350px"}),
                ],
            ),
            html.Div(
                id="detail-card",
                className="card",
                style={
                    "display": "flex",
                    "gap": "20px",
                    "flex": "1",
                    "padding": "0",
                    "overflow": "hidden",
                    "minHeight": "400px",
                },
                children=[
                    html.Div(
                        id="case-table-panel",
                        style={
                            "flex": "1",
                            "minWidth": "250px",
                            "display": "flex",
                            "flexDirection": "column",
                            "borderRight": "1px solid #333",
                            "padding": "20px",
                        },
                        children=[
                            html.Div(
                                id="current-timestamp-display",
                                style={
                                    "fontWeight": "bold",
                                    "marginBottom": "10px",
                                    "color": "#ccc",
                                    "flexShrink": "0",
                                },
                            ),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "10px",
                                    "marginBottom": "10px",
                                    "flexWrap": "wrap",
                                    "flexShrink": "0",
                                },
                                children=[
                                    dcc.Checklist(
                                        id="case-filter-check",
                                        options=[
                                            {
                                                "label": html.Span(
                                                    " 非 AC のみ",
                                                    style={
                                                        "paddingLeft": "4px",
                                                        "color": "#e0e0e0",
                                                    },
                                                ),
                                                "value": "non_ac",
                                            },
                                            {"label": " 改善", "value": "improved"},
                                            {"label": " 悪化", "value": "worsened"},
                                            {"label": " 同点", "value": "same"},
                                            {
                                                "label": " 比較不能",
                                                "value": "unavailable",
                                            },
                                            {"label": " 失敗", "value": "failed"},
                                            {
                                                "label": " Bookmark",
                                                "value": "bookmarked",
                                            },
                                        ],
                                        value=[],
                                        inline=True,
                                        labelStyle={
                                            "cursor": "pointer",
                                            "display": "flex",
                                            "alignItems": "center",
                                        },
                                        style={"fontSize": "12px"},
                                    ),
                                    html.Button(
                                        "フィルター解除",
                                        id="clear-case-filters",
                                        className="btn",
                                        n_clicks=0,
                                    ),
                                    html.Span(
                                        "各列の入力欄で絞り込み",
                                        style={"fontSize": "11px", "color": "#888"},
                                    ),
                                    html.Button(
                                        "↑ 前へ",
                                        id="previous-case",
                                        className="btn",
                                        n_clicks=0,
                                        title="現在の表示順で前のケースへ移動 (k)",
                                    ),
                                    html.Button(
                                        "↓ 次へ",
                                        id="next-case",
                                        className="btn",
                                        n_clicks=0,
                                        title="現在の表示順で次のケースへ移動 (j)",
                                    ),
                                    dcc.Checklist(
                                        id="case-column-groups",
                                        options=[
                                            {"label": " Score", "value": "score"},
                                            {"label": " Rank", "value": "rank"},
                                            {"label": " Time", "value": "time"},
                                            {"label": " Best", "value": "best"},
                                            {"label": " Params", "value": "params"},
                                        ],
                                        value=[
                                            "score",
                                            "rank",
                                            "time",
                                            "best",
                                            "params",
                                        ],
                                        inline=True,
                                        persistence=True,
                                        persistence_type="session",
                                        style={"fontSize": "12px"},
                                    ),
                                ],
                            ),
                            html.Div(
                                style={
                                    "flex": "1",
                                    "overflowY": "auto",
                                    "minHeight": "0",
                                },
                                children=[
                                    dag.AgGrid(
                                        id="file-name-table",
                                        columnDefs=config.case_column_defs(
                                            direction,
                                            read_only=read_only,
                                        ),
                                        rowData=[],
                                        getRowId="params.data.id",
                                        selectedRows=[],
                                        eventListeners={
                                            "cellKeyDown": [
                                                "caseKeyNavigation(params, setGridProps)"
                                            ]
                                        },
                                        defaultColDef={
                                            "sortable": True,
                                            "resizable": True,
                                            "filter": True,
                                            "floatingFilter": True,
                                            "minWidth": 80,
                                        },
                                        dashGridOptions={
                                            "theme": config.GRID_THEME,
                                            "animateRows": False,
                                            "rowSelection": {
                                                "mode": "singleRow",
                                                "enableClickSelection": True,
                                                "checkboxes": False,
                                                "headerCheckbox": False,
                                            },
                                            "multiSortKey": "ctrl",
                                        },
                                        persistence=True,
                                        persistence_type="session",
                                        persisted_props=["filterModel", "columnState"],
                                        style={
                                            "width": "100%",
                                            "height": "100%",
                                        },
                                    )
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        id="case-detail-panel",
                        style={
                            "flex": "3",
                            "display": "flex",
                            "flexDirection": "column",
                            "height": "100%",
                            "minWidth": "0",
                        },
                        children=[
                            dcc.Tabs(
                                id="detail-tabs",
                                value="tab-text",
                                className="custom-tabs",
                                children=[
                                    dcc.Tab(
                                        label="標準出力 (err/out)",
                                        value="tab-text",
                                        className="custom-tab",
                                        selected_className="custom-tab--selected",
                                    ),
                                    dcc.Tab(
                                        label="入力 (in)",
                                        value="tab-in",
                                        className="custom-tab",
                                        selected_className="custom-tab--selected",
                                    ),
                                    dcc.Tab(
                                        label="ソースコード",
                                        value="tab-src",
                                        className="custom-tab",
                                        selected_className="custom-tab--selected",
                                    ),
                                    dcc.Tab(
                                        label="Diff",
                                        value="tab-diff",
                                        className="custom-tab",
                                        selected_className="custom-tab--selected",
                                    ),
                                    dcc.Tab(
                                        label="ビジュアライザ",
                                        value="tab-vis",
                                        className="custom-tab",
                                        selected_className="custom-tab--selected",
                                    ),
                                ],
                            ),
                            html.Div(
                                style={
                                    "display": "flex",
                                    "alignItems": "center",
                                    "gap": "10px",
                                    "padding": "8px 20px 0",
                                    "flexWrap": "wrap",
                                },
                                children=[
                                    dcc.Input(
                                        id="detail-search",
                                        type="text",
                                        placeholder="表示内容を検索",
                                        debounce=True,
                                        persistence=True,
                                        persistence_type="session",
                                        style={"minWidth": "220px"},
                                    ),
                                    dcc.Checklist(
                                        id="detail-view-options",
                                        options=[
                                            {"label": " 行を折り返す", "value": "wrap"},
                                            {"label": " 全文表示", "value": "full"},
                                        ],
                                        value=["wrap"],
                                        inline=True,
                                        persistence=True,
                                        persistence_type="session",
                                        style={"fontSize": "12px"},
                                    ),
                                    html.Span(
                                        id="detail-search-result",
                                        style={"fontSize": "12px", "color": "#aaa"},
                                    ),
                                ],
                            ),
                            html.Div(
                                id="tab-content",
                                style={
                                    "flex": "1",
                                    "padding": "20px",
                                    "overflowY": "auto",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "minHeight": "0",
                                },
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def build_layout(direction: str, read_only: bool = False) -> Component:
    return html.Div(
        className="layout-container",
        children=[
            dcc.Store(id="base-store"),
            dcc.Store(id="base-request-store"),
            dcc.Store(id="table-data", data=[]),
            dcc.Store(id="target-ts-store", data=None),
            dcc.Store(id="result-version-store", data=0),
            dcc.Store(id="pending-delete-store"),
            dcc.Store(id="delete-result-store"),
            dcc.Store(id="run-edit-result-store"),
            dcc.Store(id="case-edit-result-store"),
            dcc.ConfirmDialog(
                id="delete-confirm",
                message="この実行結果を削除しますか",
            ),
            html.Div(
                "Tailscale 共有中 読み取り専用",
                style={
                    "display": "block" if read_only else "none",
                    "backgroundColor": "#183a4a",
                    "color": "#81d4fa",
                    "padding": "6px 20px",
                    "fontSize": "12px",
                },
            ),
            html.Div(
                id="status-banner",
                style={"display": "none"},
            ),
            _build_sidebar(direction, read_only),
            _build_main(direction, read_only),
        ],
    )
