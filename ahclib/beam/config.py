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
