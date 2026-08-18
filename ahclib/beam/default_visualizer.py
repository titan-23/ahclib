from dash import html
from dash.development.base_component import Component


def generate_board_visual(action_seq: str) -> Component:
    return html.Div(
        "visualizer.py が見つかりません。work/visualizer.py をカスタマイズしてください。",
        style={"color": "#aaa", "padding": "10px"},
    )
