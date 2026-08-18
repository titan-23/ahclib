import os
from copy import deepcopy

BASE_PATH = "ahclib_results/all_tests"
FILE_NAME = "result.csv"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# CSS はビームサーチ可視化と同じディレクトリから読み込む
ASSETS_PATH = os.path.join(CURRENT_DIR, "..", "assets")


def vis_html_path() -> str:
    return os.path.join(os.getcwd(), "visualizer.html")


def in_dir() -> str:
    return "./in"


GRID_THEME = {
    "function": """themeQuartz.withParams({
        backgroundColor: '#1e1e1e',
        foregroundColor: '#e0e0e0',
        headerBackgroundColor: '#2d2d2d',
        headerTextColor: '#e0e0e0',
        oddRowBackgroundColor: '#242424',
        borderColor: '#444444',
        accentColor: '#29b6f6',
        selectedRowBackgroundColor: 'rgba(41, 182, 246, 0.20)',
        inputBackgroundColor: '#2d2d2d',
        inputTextColor: '#e0e0e0',
        fontSize: 12,
        rowHeight: 34,
        headerHeight: 34
    })"""
}

NUMBER_FORMATTER = {
    "function": "params.value == null ? '' : d3.format(',.12~f')(params.value)"
}
DECIMAL_FORMATTER = {
    "function": "params.value == null ? '' : d3.format(',.3f')(params.value)"
}

RUN_COLUMN_DEFS = [
    {
        "headerName": "Base",
        "field": "is_base_str",
        "width": 58,
        "pinned": "left",
        "filter": False,
        "sortable": False,
        "cellStyle": {"textAlign": "center", "cursor": "pointer", "color": "#ffca28"},
    },
    {
        "headerName": "実行日時",
        "field": "formatted",
        "width": 128,
        "filter": "agTextColumnFilter",
    },
    {
        "headerName": "Total",
        "headerTooltip": "AHCSettings.get_score",
        "field": "aggregate_score",
        "type": "numericColumn",
        "width": 108,
        "valueFormatter": NUMBER_FORMATTER,
    },
    {
        "headerName": "RelGeo",
        "headerTooltip": "Base との相対値の幾何平均",
        "field": "rel_geo",
        "type": "numericColumn",
        "width": 72,
        "valueFormatter": DECIMAL_FORMATTER,
    },
    {
        "headerName": "Median",
        "field": "median_score",
        "type": "numericColumn",
        "width": 100,
        "valueFormatter": NUMBER_FORMATTER,
    },
    {
        "headerName": "IQR",
        "field": "iqr_score",
        "type": "numericColumn",
        "width": 90,
        "valueFormatter": NUMBER_FORMATTER,
    },
    {
        "headerName": "CI95 ±",
        "headerTooltip": "算術平均の 95% 信頼区間の半幅 (正規近似)",
        "field": "ci95_score",
        "type": "numericColumn",
        "width": 90,
        "valueFormatter": NUMBER_FORMATTER,
    },
    {
        "headerName": "Rel N/A",
        "field": "rel_missing",
        "type": "numericColumn",
        "width": 76,
    },
    {
        "headerName": "Std",
        "field": "std_score",
        "type": "numericColumn",
        "width": 90,
        "valueFormatter": NUMBER_FORMATTER,
    },
    {
        "headerName": "Cases",
        "field": "case_count",
        "type": "numericColumn",
        "width": 68,
    },
    {
        "headerName": "NG",
        "field": "ng_cnt",
        "type": "numericColumn",
        "width": 52,
        "cellStyle": {"color": "#e57373", "fontWeight": "bold"},
    },
    {
        "headerName": "Tag",
        "field": "tag",
        "editable": True,
        "singleClickEdit": True,
        "width": 90,
        "filter": "agTextColumnFilter",
        "cellStyle": {"backgroundColor": "#2a2a2a"},
    },
    {
        "headerName": "Memo",
        "field": "memo",
        "editable": True,
        "singleClickEdit": True,
        "width": 120,
        "filter": "agTextColumnFilter",
        "cellStyle": {"backgroundColor": "#2a2a2a"},
    },
    {
        "headerName": "",
        "field": "delete_btn",
        "width": 48,
        "pinned": "right",
        "filter": False,
        "sortable": False,
        "cellStyle": {"textAlign": "center", "cursor": "pointer", "color": "#e57373"},
    },
]


def run_column_defs(
    direction: str,
    read_only: bool = False,
) -> list[dict]:
    """実行一覧の列定義を表示モードに合わせて返す"""
    columns = deepcopy(RUN_COLUMN_DEFS)
    improve_operator = "<" if direction == "minimize" else ">"
    worsen_operator = ">" if direction == "minimize" else "<"
    for column in columns:
        if column.get("field") == "rel_geo":
            column["cellStyle"] = {
                "styleConditions": [
                    {
                        "condition": (
                            f"params.value != null && params.value {improve_operator} 1"
                        ),
                        "style": {"color": "#81c784", "fontWeight": "bold"},
                    },
                    {
                        "condition": (
                            f"params.value != null && params.value {worsen_operator} 1"
                        ),
                        "style": {"color": "#e57373", "fontWeight": "bold"},
                    },
                ]
            }
    if not read_only:
        return columns

    columns = [column for column in columns if column.get("field") != "delete_btn"]
    for column in columns:
        if column.get("field") in ("memo", "tag"):
            column["editable"] = False
    return columns


def _delta_style(direction: str) -> dict:
    improve_operator = "<" if direction == "minimize" else ">"
    worsen_operator = ">" if direction == "minimize" else "<"
    return {
        "styleConditions": [
            {
                "condition": f"params.value {improve_operator} 0",
                "style": {"color": "#81c784", "fontWeight": "bold"},
            },
            {
                "condition": f"params.value {worsen_operator} 0",
                "style": {"color": "#e57373", "fontWeight": "bold"},
            },
        ]
    }


def case_column_defs(
    direction: str,
    parameter_specs: list[tuple[object, str, bool]] | None = None,
    visible_groups: list[str] | None = None,
    read_only: bool = False,
) -> list[dict]:
    """最適化方向に合わせた詳細結果の列定義を返す"""
    default_groups = ["score", "rank", "time", "best", "params"]
    visible = set(default_groups if visible_groups is None else visible_groups)
    parameter_columns = []
    for name, field, is_numeric in parameter_specs or []:
        column = {
            "headerName": str(name),
            "headerTooltip": f"parse_input_params: {name}",
            "field": field,
            "filter": "agNumberColumnFilter" if is_numeric else "agTextColumnFilter",
            "hide": "params" not in visible,
        }
        if is_numeric:
            column.update(
                type="numericColumn",
                valueFormatter=NUMBER_FORMATTER,
            )
        parameter_columns.append(column)

    fixed_columns = [
        {
            "headerName": "★",
            "field": "bookmark_str",
            "width": 54,
            "pinned": "left",
            "filter": False,
            "cellStyle": {
                "textAlign": "center",
                "cursor": "pointer",
                "color": "#ffca28",
            },
        },
        {
            "headerName": "Case Memo",
            "field": "case_memo",
            "editable": True,
            "singleClickEdit": True,
            "minWidth": 135,
            "filter": "agTextColumnFilter",
            "cellStyle": {"backgroundColor": "#2a2a2a"},
        },
        {
            "headerName": "Case",
            "field": "name",
            "pinned": "left",
            "minWidth": 115,
            "filter": "agTextColumnFilter",
        },
        {
            "headerName": "State",
            "field": "state",
            "width": 88,
            "pinned": "left",
            "filter": "agTextColumnFilter",
            "cellStyle": {
                "styleConditions": [
                    {
                        "condition": "params.value != 'AC' && params.value != ''",
                        "style": {"color": "#e57373", "fontWeight": "bold"},
                    }
                ]
            },
        },
        {
            "headerName": "Base State",
            "field": "base_state",
            "width": 105,
            "filter": "agTextColumnFilter",
            "hide": "score" not in visible,
        },
        {
            "headerName": "判定",
            "field": "comparison",
            "width": 105,
            "filter": "agTextColumnFilter",
            "hide": "score" not in visible,
            "cellStyle": {
                "styleConditions": [
                    {
                        "condition": "params.value == '改善'",
                        "style": {"color": "#81c784", "fontWeight": "bold"},
                    },
                    {
                        "condition": "params.value == '悪化'",
                        "style": {"color": "#e57373", "fontWeight": "bold"},
                    },
                ]
            },
        },
        {
            "headerName": "Score",
            "field": "score",
            "type": "numericColumn",
            "valueFormatter": NUMBER_FORMATTER,
            "hide": "score" not in visible,
        },
        {
            "headerName": "Base Score",
            "field": "base_score",
            "type": "numericColumn",
            "valueFormatter": NUMBER_FORMATTER,
            "hide": "score" not in visible,
        },
        {
            "headerName": "Δ Score",
            "field": "score_delta",
            "type": "numericColumn",
            "valueFormatter": NUMBER_FORMATTER,
            "cellStyle": _delta_style(direction),
            "hide": "score" not in visible,
        },
        {
            "headerName": "|Δ Score|",
            "field": "abs_score_delta",
            "type": "numericColumn",
            "valueFormatter": NUMBER_FORMATTER,
            "hide": "score" not in visible,
        },
        {
            "headerName": "Rel",
            "field": "rel",
            "type": "numericColumn",
            "valueFormatter": DECIMAL_FORMATTER,
            "hide": "score" not in visible,
        },
        {
            "headerName": "|Rel-1|",
            "field": "relative_gap",
            "type": "numericColumn",
            "valueFormatter": DECIMAL_FORMATTER,
            "hide": "score" not in visible,
        },
        {
            "headerName": "Rank",
            "field": "rank",
            "type": "numericColumn",
            "width": 80,
            "hide": "rank" not in visible,
        },
        {
            "headerName": "Base Rank",
            "field": "base_rank",
            "type": "numericColumn",
            "width": 105,
            "hide": "rank" not in visible,
        },
        {
            "headerName": "Δ Rank",
            "field": "rank_delta",
            "type": "numericColumn",
            "width": 92,
            "cellStyle": _delta_style("minimize"),
            "hide": "rank" not in visible,
        },
        {
            "headerName": "Time",
            "field": "time",
            "type": "numericColumn",
            "valueFormatter": DECIMAL_FORMATTER,
            "hide": "time" not in visible,
        },
        {
            "headerName": "Base Time",
            "field": "base_time",
            "type": "numericColumn",
            "valueFormatter": DECIMAL_FORMATTER,
            "hide": "time" not in visible,
        },
        {
            "headerName": "Δ Time",
            "field": "time_delta",
            "type": "numericColumn",
            "valueFormatter": DECIMAL_FORMATTER,
            "cellStyle": _delta_style("minimize"),
            "hide": "time" not in visible,
        },
        {
            "headerName": "Best",
            "field": "best",
            "type": "numericColumn",
            "valueFormatter": NUMBER_FORMATTER,
            "hide": "best" not in visible,
        },
    ]
    columns = fixed_columns[:6] + parameter_columns + fixed_columns[6:]
    if read_only:
        for column in columns:
            if column.get("field") == "case_memo":
                column["editable"] = False
            if column.get("field") == "bookmark_str":
                column["cellStyle"] = {"textAlign": "center", "color": "#ffca28"}
    return columns
