from dash import html
from functools import cache

# beam_config.py からテーマカラーをインポートできる場合は以下を使用します
# from beam_config import DARK_THEME
# できない場合は直接色を指定します
DARK_THEME = {"accent": "#1976d2"}


@cache
def generate_board_visual(action_seq: str):
    """
    Action列を受け取り、盤面のDashコンポーネントを生成して返します。
    """
    # 実際の初期盤面に書き換えてください
    initial_board = [[8, 1, 13, 0], [3, 9, 10, 5], [7, 14, 6, 2], [11, 12, 15, 4]]

    N = len(initial_board)

    # 盤面をディープコピー
    board = [row[:] for row in initial_board]

    # 空きマス(0)の初期位置を特定
    y, x = -1, -1
    for i in range(N):
        for j in range(N):
            if board[i][j] == 0:
                y, x = i, j
                break
        if y != -1:
            break

    # Action列のシミュレーション
    for act in action_seq:
        ny, nx = y, x
        if act == "D":
            ny += 1
        elif act == "U":
            ny -= 1
        elif act == "R":
            nx += 1
        elif act == "L":
            nx -= 1

        if 0 <= ny < N and 0 <= nx < N:
            board[y][x], board[ny][nx] = board[ny][nx], board[y][x]
            y, x = ny, nx

    # 描画用コンポーネントの生成
    cells = []
    for row in board:
        for val in row:
            cell_style = {
                "width": "40px",
                "height": "40px",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "center",
                "fontWeight": "bold",
                "fontSize": "16px",
                "color": "#ffffff",
                "backgroundColor": DARK_THEME["accent"] if val != 0 else "#1e1e1e",
                "border": "1px solid #444",
                "boxSizing": "border-box",
            }
            cells.append(html.Div(str(val) if val != 0 else "", style=cell_style))

    state_visual = html.Div(
        cells,
        style={
            "display": "grid",
            "gridTemplateColumns": f"repeat({N}, 40px)",
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
