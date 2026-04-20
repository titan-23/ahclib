import os

DARK_THEME = {
    "background": "#1e1e1e",
    "panel": "#252526",
    "text": "#d4d4d4",
    "border": "#333",
    "accent": "#1976d2",
    "pruned": "#555555",
    "invalid": "#d32f2f",
    "highlight": "#ffeb3b",
    "bookmark": "#ff9800",
    "inf": "#8e24aa",
    "answer": "#ffeb3b",
}

BASE_STYLESHEET = [
    {
        "selector": "node",
        "style": {
            "label": "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "10px",
            "width": "60px",
            "height": "30px",
            "shape": "rectangle",
            "color": "#ffffff",
            "text-wrap": "wrap",
            "border-width": "0px",
        },
    },
    {"selector": ".status-active", "style": {"background-color": DARK_THEME["accent"]}},
    {
        "selector": ".status-pruned",
        "style": {
            "background-color": DARK_THEME["pruned"],
            "width": "20px",
            "height": "20px",
            "font-size": "0px",
        },
    },
    {
        "selector": ".status-invalid",
        "style": {
            "background-color": DARK_THEME["invalid"],
            "width": "8px",
            "height": "8px",
            "font-size": "0px",
        },
    },
    {
        "selector": ".folded",
        "style": {
            "border-width": "3px",
            "border-color": "#ffffff",
            "border-style": "double",
        },
    },
    {
        "selector": ".bookmarked",
        "style": {
            "border-width": "4px",
            "border-color": DARK_THEME["bookmark"],
            "border-style": "solid",
        },
    },
    {
        "selector": ".searched",
        "style": {"border-width": "4px", "border-color": "#00ff00"},
    },
    {
        "selector": ".heatmap-node",
        "style": {
            "background-color": "data(bg_color)",
            "color": "#ffffff",
            "text-outline-width": "0px",
            "font-weight": "bold",
        },
    },
    {
        "selector": "edge",
        "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "width": 4,
            "line-color": "#9e9e9e",
            "target-arrow-color": "#9e9e9e",
            "events": "no",
        },
    },
    {
        "selector": ".dummy-edge",
        "style": {
            "line-style": "dashed",
            "line-color": "#9e9e9e",
            "target-arrow-color": "#9e9e9e",
        },
    },
    {
        "selector": ".status-answer",
        "style": {
            "background-color": DARK_THEME["answer"],
            "shape": "star",
            "width": "50px",
            "height": "50px",
            "border-width": "2px",
            "border-color": "#ffffff",
            "z-index": "100",
        },
    },
]

tab_style = {
    "backgroundColor": "#2d2d30",
    "color": "#d4d4d4",
    "border": f'1px solid {DARK_THEME["border"]}',
    "padding": "10px",
    "cursor": "pointer",
}

tab_selected_style = {
    "backgroundColor": DARK_THEME["accent"],
    "color": "#ffffff",
    "border": f'1px solid {DARK_THEME["accent"]}',
    "padding": "10px",
    "cursor": "pointer",
}


def generate_assets():
    os.makedirs("assets", exist_ok=True)
    with open("assets/beam_custom.css", "w", encoding="utf-8") as f:
        f.write(
            """
        html, body {
            margin: 0;
            padding: 0;
            background-color: #1e1e1e;
        }

        .modern-btn {
            background-color: #1976d2; color: #ffffff; border: none; border-radius: 4px;
            padding: 6px 12px; cursor: pointer; font-weight: bold;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3); transition: background-color 0.2s, transform 0.1s;
        }
        .modern-btn:hover { background-color: #1565c0; }
        .modern-btn:active { transform: scale(0.95); }

        .right-panel {
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            background-color: #252526; display: flex; flex-direction: column; z-index: 1000;
        }
        .right-panel-pinned {
            width: 450px; min-width: 450px; flex: none; position: relative;
            transform: translateX(0); border-left: 1px solid #333;
        }
        .right-panel-unpinned {
            position: absolute; right: 0; top: 0; bottom: 0; width: 450px;
            box-shadow: -4px 0 15px rgba(0,0,0,0.5); transform: translateX(100%);
        }
        .right-panel-unpinned.open { transform: translateX(0); }

        .panel-toggle-btn {
            position: absolute; left: -24px; top: 50%; transform: translateY(-50%);
            width: 24px; height: 48px; background-color: #333; color: white;
            border: 1px solid #444; border-right: none; border-radius: 4px 0 0 4px;
            cursor: pointer; display: flex; align-items: center; justify-content: center;
            z-index: 1001; box-shadow: -2px 0 4px rgba(0,0,0,0.3);
        }
        .panel-toggle-btn:hover { background-color: #444; }
        """
        )
