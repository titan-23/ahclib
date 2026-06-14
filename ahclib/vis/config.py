import os

BASE_PATH = "ahclib_results/all_tests"
FILE_NAME = "result.csv"

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# assets は ahclib/assets/ を beam と共有する
ASSETS_PATH = os.path.join(CURRENT_DIR, "..", "assets")


def vis_html_path() -> str:
    return os.path.join(os.getcwd(), "visualizer.html")


def in_dir() -> str:
    return "./in"


TABLE_STYLE_CELL = {
    "textAlign": "left",
    "padding": "6px",
    "fontSize": "12px",
    "backgroundColor": "#1e1e1e",
    "color": "#e0e0e0",
    "border": "1px solid #444",
}

TABLE_STYLE_HEADER = {
    "fontWeight": "bold",
    "backgroundColor": "#2d2d2d",
    "color": "#e0e0e0",
    "border": "1px solid #444",
}

TIMESTAMP_TABLE_COLUMNS = [
    {"name": "Base", "id": "is_base_str"},
    {"name": "実行日時", "id": "formatted"},
    {
        "name": "Ave",
        "id": "average_score",
        "type": "numeric",
        "format": {"specifier": ".2f"},
    },
    {
        "name": "Rel",
        "id": "rel_ave",
        "type": "numeric",
        "format": {"specifier": ".3f"},
    },
    {
        "name": "Std",
        "id": "std_score",
        "type": "numeric",
        "format": {"specifier": ".2f"},
    },
    {"name": "NG", "id": "ng_cnt", "type": "numeric"},
    {
        "name": "Memo",
        "id": "memo",
        "editable": True,
    },
    {"name": "", "id": "delete_btn"},
]


def timestamp_style_data_conditional(direction: str) -> list:
    """direction に応じて相対スコアの改善・悪化の色を割り当てる"""
    return [
        {
            "if": {"state": "selected"},
            "backgroundColor": "#3a3f47",
            "border": "1px solid #666",
        },
        {
            "if": {"state": "active"},
            "backgroundColor": "#3a3f47",
            "border": "1px solid #666",
        },
        {
            "if": {"column_id": "is_base_str"},
            "cursor": "pointer",
            "textAlign": "center",
            "width": "40px",
            "fontSize": "14px",
        },
        {
            "if": {
                "column_id": "is_base_str",
                "filter_query": "{is_base_str} = '★'",
            },
            "color": "#ffca28",
        },
        {
            "if": {
                "column_id": "is_base_str",
                "filter_query": "{is_base_str} = '・'",
            },
            "color": "#666666",
        },
        {
            "if": {"column_id": "delete_btn"},
            "cursor": "pointer",
            "textAlign": "center",
            "width": "30px",
            "fontSize": "14px",
            "color": "#e57373",
        },
        {
            "if": {
                "column_id": "ng_cnt",
                "filter_query": "{ng_cnt} > 0",
            },
            "color": "#e57373",
            "fontWeight": "bold",
        },
        {
            "if": {"column_id": "memo"},
            "minWidth": "130px",
            "maxWidth": "200px",
            "textOverflow": "ellipsis",
            "overflow": "hidden",
            "whiteSpace": "nowrap",
            "backgroundColor": "#2a2a2a",
        },
        {
            "if": {
                "column_id": "rel_ave",
                "filter_query": (
                    "{rel_ave} < 1.0" if direction == "minimize" else "{rel_ave} > 1.0"
                ),
            },
            "backgroundColor": "rgba(46, 125, 50, 0.3)",
            "color": "#81c784",
        },
        {
            "if": {
                "column_id": "rel_ave",
                "filter_query": (
                    "{rel_ave} > 1.0" if direction == "minimize" else "{rel_ave} < 1.0"
                ),
            },
            "backgroundColor": "rgba(183, 28, 28, 0.3)",
            "color": "#e57373",
        },
    ]


FILE_TABLE_COLUMNS = [
    {"name": "Case", "id": "name"},
    {"name": "State", "id": "state"},
    {"name": "Score", "id": "score", "type": "numeric"},
    {
        "name": "Time",
        "id": "time",
        "type": "numeric",
        "format": {"specifier": ".3f"},
    },
    {"name": "Best", "id": "best", "type": "numeric"},
    {
        "name": "Rel",
        "id": "rel",
        "type": "numeric",
        "format": {"specifier": ".3f"},
    },
]

FILE_TABLE_STYLE_CELL = {
    "textAlign": "left",
    "padding": "8px",
    "fontFamily": "monospace",
    "fontSize": "13px",
    "backgroundColor": "#1e1e1e",
    "color": "#e0e0e0",
    "border": "1px solid #444",
}
