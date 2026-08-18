from functools import cache

from dash import html
from dash.development.base_component import Component

# beam_config.py を利用する場合は次の import を有効にする
# from beam_config import DARK_THEME
# 単独で使う場合はここで色を指定する
DARK_THEME = {"accent": "#1976d2"}


@cache
def generate_board_visual(action_seq: str) -> Component:
    """操作列を適用した盤面を Dash コンポーネントとして返す"""
    # 問題に合わせて初期盤面を書き換える
    initial_board = [[8, 1, 13, 0], [3, 9, 10, 5], [7, 14, 6, 2], [11, 12, 15, 4]]

    board_size = len(initial_board)

    # 行ごとに複製し、元の盤面を変更しないようにする
    board = [row[:] for row in initial_board]

    empty_row, empty_column = -1, -1
    for i in range(board_size):
        for j in range(board_size):
            if board[i][j] == 0:
                empty_row, empty_column = i, j
                break
        if empty_row != -1:
            break

    for action in action_seq:
        next_row, next_column = empty_row, empty_column
        if action == "D":
            next_row += 1
        elif action == "U":
            next_row -= 1
        elif action == "R":
            next_column += 1
        elif action == "L":
            next_column -= 1

        if 0 <= next_row < board_size and 0 <= next_column < board_size:
            board[empty_row][empty_column], board[next_row][next_column] = (
                board[next_row][next_column],
                board[empty_row][empty_column],
            )
            empty_row, empty_column = next_row, next_column

    cells = []
    for row in board:
        for value in row:
            cell_style = {
                "width": "40px",
                "height": "40px",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "center",
                "fontWeight": "bold",
                "fontSize": "16px",
                "color": "#ffffff",
                "backgroundColor": (DARK_THEME["accent"] if value != 0 else "#1e1e1e"),
                "border": "1px solid #444",
                "boxSizing": "border-box",
            }
            cells.append(html.Div(str(value) if value != 0 else "", style=cell_style))

    state_visual = html.Div(
        cells,
        style={
            "display": "grid",
            "gridTemplateColumns": f"repeat({board_size}, 40px)",
            "gridGap": "2px",
            "backgroundColor": "#333",
            "padding": "4px",
            "width": "max-content",
            "margin": "0 auto",
        },
    )

    return html.Div(
        style={"padding": "10px", "color": "#d4d4d4"},
        children=[
            html.H4("盤面状態", style={"margin": "0 0 10px 0"}),
            state_visual,
        ],
    )
