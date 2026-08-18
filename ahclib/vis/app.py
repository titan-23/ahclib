import json
import logging
import os
import threading

from dash import Dash
from flask import Response, abort, request

from ..tailscale_serve import TailscaleServe
from . import config
from .callbacks import register_callbacks
from .data import ResultStore, get_ahc_setting
from .layout import build_layout


def _javascript_value(value: str) -> str:
    """HTML 内の script へ安全に埋め込める JSON 文字列を返す"""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _register_visualizer_route(app: Dash, store: ResultStore) -> None:
    @app.server.get("/_ahclib_visualizer")
    def visualizer() -> Response:
        timestamp = request.args.get("timestamp", "")
        case_id = request.args.get("case_id", "")
        result = store.snapshot().case(timestamp, case_id)
        if result is None:
            abort(404)

        template = store.visualizer_template()
        if not template:
            abort(404)

        filename = str(result.get("name") or "")
        input_filename = str(result.get("filename") or filename)
        input_text = store.in_file(input_filename)
        _, output_text = store.out_err(timestamp, filename)
        if output_text == "(out ファイルなし)":
            output_text = ""

        data_script = (
            "<script>\n"
            f"const INPUT_DATA = {_javascript_value(input_text)};\n"
            f"const OUTPUT_DATA = {_javascript_value(output_text)};\n"
            "</script>"
        )
        if "</body>" in template:
            document = template.replace("</body>", f"{data_script}\n</body>", 1)
        else:
            document = f"{template}\n{data_script}"

        response = Response(document, content_type="text/html; charset=utf-8")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'unsafe-inline'; "
            "style-src 'unsafe-inline'; "
            "img-src data: blob:; "
            "font-src data:"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def create_app(read_only: bool = False) -> Dash:
    """テスト結果を表示する Dash アプリを構築する"""
    direction = get_ahc_setting("direction", "minimize")
    store = ResultStore(direction=direction, read_only=read_only)

    if not os.path.exists(config.ASSETS_PATH):
        os.makedirs(config.ASSETS_PATH, exist_ok=True)

    app = Dash(__name__, assets_folder=config.ASSETS_PATH)
    app.layout = build_layout(direction, read_only=read_only)
    register_callbacks(app, store)
    _register_visualizer_route(app, store)
    return app


def run_vis(tailscale: bool = False, port: int = 8050) -> None:
    """通常の vis をローカルまたは tailnet 内で起動する"""
    if not tailscale:
        create_app().run(host="127.0.0.1", port=port, debug=False)
        return

    from werkzeug.serving import make_server

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = create_app(read_only=True)
    server = make_server("127.0.0.1", port, app.server, threaded=True)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    tailscale_serve = None
    try:
        target = f"http://127.0.0.1:{port}"
        print(f"local URL     : {target}")
        print("remote access : starting Tailscale Serve ...")
        tailscale_serve = TailscaleServe.start(target)
        print(f"private URL   : {tailscale_serve.private_url}")
        print("access scope  : Tailscale tailnet only (not public)")
        print("mode          : read-only")
        try:
            input("Press Enter to close vis and exit...")
        except (EOFError, KeyboardInterrupt):
            pass
    finally:
        if tailscale_serve is not None:
            tailscale_serve.stop()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


if __name__ == "__main__":
    run_vis()
