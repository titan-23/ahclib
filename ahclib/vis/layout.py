from dash import dcc, html, dash_table

from . import config


def _graph_type_radio():
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
        style={"display": "flex", "gap": "12px"},
        labelStyle={
            "cursor": "pointer",
            "color": "#e0e0e0",
            "display": "flex",
            "alignItems": "center",
            "fontSize": "13px",
        },
    )


def _build_sidebar(direction):
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
                            dash_table.DataTable(
                                id="timestamp-table",
                                columns=config.TIMESTAMP_TABLE_COLUMNS,
                                style_table={"width": "100%"},
                                style_cell=config.TABLE_STYLE_CELL,
                                style_header=config.TABLE_STYLE_HEADER,
                                style_data_conditional=config.timestamp_style_data_conditional(
                                    direction
                                ),
                                row_selectable="multi",
                                selected_rows=[],
                            )
                        ],
                    ),
                    html.Div(
                        "※ Memo列をクリックでメモを編集・自動保存できます",
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


def _build_main():
    return html.Div(
        className="main-content",
        children=[
            html.Div(
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
                                                    " Y軸をLogスケール",
                                                    style={
                                                        "paddingLeft": "4px",
                                                        "color": "#e0e0e0",
                                                    },
                                                ),
                                                "value": "log",
                                            }
                                        ],
                                        value=[],
                                        labelStyle={
                                            "cursor": "pointer",
                                            "display": "flex",
                                            "alignItems": "center",
                                        },
                                        style={"fontSize": "13px"},
                                    ),
                                ],
                            ),
                        ],
                    ),
                    dcc.Graph(id="score-comparison-graph", style={"height": "350px"}),
                ],
            ),
            html.Div(
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
                            dcc.Checklist(
                                id="case-filter-check",
                                options=[
                                    {
                                        "label": html.Span(
                                            " 非ACのみ",
                                            style={
                                                "paddingLeft": "4px",
                                                "color": "#e0e0e0",
                                            },
                                        ),
                                        "value": "non_ac",
                                    }
                                ],
                                value=[],
                                labelStyle={
                                    "cursor": "pointer",
                                    "display": "flex",
                                    "alignItems": "center",
                                },
                                style={
                                    "fontSize": "12px",
                                    "marginBottom": "10px",
                                    "flexShrink": "0",
                                },
                            ),
                            html.Div(
                                style={
                                    "flex": "1",
                                    "overflowY": "auto",
                                    "minHeight": "0",
                                },
                                children=[
                                    dash_table.DataTable(
                                        id="file-name-table",
                                        columns=config.FILE_TABLE_COLUMNS,
                                        sort_action="native",
                                        style_cell=config.FILE_TABLE_STYLE_CELL,
                                        style_header=config.TABLE_STYLE_HEADER,
                                        cell_selectable=True,
                                        style_as_list_view=True,
                                    )
                                ],
                            ),
                        ],
                    ),
                    html.Div(
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
                                        label="Diff (ソースコード)",
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


def build_layout(direction):
    return html.Div(
        className="layout-container",
        children=[
            dcc.Store(id="base-store"),
            dcc.Store(id="table-data", data=[]),
            dcc.Store(id="prev-selected-rows", data=[]),
            dcc.Store(id="target-ts-store", data=None),
            html.Div(id="dummy-output", style={"display": "none"}),
            _build_sidebar(direction),
            _build_main(),
        ],
    )
