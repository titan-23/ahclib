import os

from dash import Dash

from . import config
from .data import ResultStore, get_ahc_setting
from .layout import build_layout
from .callbacks import register_callbacks


def create_app():
    """vis ダッシュボードの Dash アプリを構築して返す"""
    direction = get_ahc_setting("direction", "minimize")
    store = ResultStore(direction=direction)

    if not os.path.exists(config.ASSETS_PATH):
        os.makedirs(config.ASSETS_PATH, exist_ok=True)

    app = Dash(__name__, assets_folder=config.ASSETS_PATH)
    app.layout = build_layout(direction)
    register_callbacks(app, store)
    return app


if __name__ == "__main__":
    create_app().run(debug=False)
