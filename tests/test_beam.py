import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ahclib.beam.app as beam_app
from ahclib.beam.app import create_app
from ahclib.beam.data import load_and_process_data
from ahclib.beam.default_visualizer import generate_board_visual
from ahclib.beam.store import LRUCache


def _history() -> dict:
    return {
        "INF": 1_000_000,
        "nodes": [
            {
                "node_id": 0,
                "parent_id": -1,
                "turn": 1,
                "score": 10,
                "hash": 100,
                "action": "A",
                "state_info": {},
                "status": 0,
            },
            {
                "node_id": 1,
                "parent_id": -1,
                "turn": 1,
                "score": 20,
                "hash": 101,
                "action": "B",
                "state_info": {},
                "status": 1,
            },
            {
                "node_id": 2,
                "parent_id": 0,
                "turn": 2,
                "score": 11,
                "hash": 102,
                "action": "C",
                "state_info": {},
                "status": 0,
            },
            {
                "node_id": 3,
                "parent_id": 0,
                "turn": 2,
                "score": 30,
                "hash": 103,
                "action": "D",
                "state_info": {},
                "status": 1,
            },
            {
                "node_id": 4,
                "parent_id": 2,
                "turn": 3,
                "score": 12,
                "hash": 104,
                "action": "E",
                "state_info": {},
                "status": 0,
                "is_answer": True,
            },
        ],
        "snapshots": [
            {"turn": 1, "active_node_ids": [0], "threshold": 15},
            {"turn": 2, "active_node_ids": [2], "threshold": 25},
            {"turn": 3, "active_node_ids": [4], "threshold": 35},
        ],
    }


class BeamAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_path = os.path.join(self.temp_dir.name, "history.json")
        with open(self.history_path, "w", encoding="utf-8") as history_file:
            json.dump(_history(), history_file)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _callbacks(self):
        app = create_app(generate_board_visual, self.history_path)
        callbacks = {
            item["callback"].__wrapped__.__name__: item["callback"].__wrapped__
            for item in app.callback_map.values()
        }
        callbacks["load_data"](0, "")
        return app, callbacks

    def test_processed_data_has_turn_indices(self) -> None:
        processed, max_turn, marks = load_and_process_data(self.history_path)

        self.assertEqual(max_turn, 3)
        self.assertEqual(marks, {})
        self.assertEqual(processed["node_turns"], (1, 2, 3))
        self.assertEqual(processed["active_turns"], (1, 2, 3))
        self.assertEqual(processed["pruned_ids"], ("1", "3"))
        self.assertEqual(
            [
                [node["sid"] for node in processed["nodes_by_turn"][turn]]
                for turn in (1, 2, 3)
            ],
            [["0", "1"], ["2", "3"], ["4"]],
        )

    def test_tree_elements_match_existing_display(self) -> None:
        _, callbacks = self._callbacks()
        with patch.object(beam_app, "callback_context", SimpleNamespace(triggered=[])):
            elements, _ = callbacks["update_elements"](
                {"ts": 0},
                [2, 3],
                [],
                [],
                [],
                0,
                "tab-tree",
                "LR",
                0,
                "",
                [],
            )

        self.assertEqual(
            elements,
            [
                {
                    "data": {"id": "-1", "label": "Start"},
                    "classes": "status-active",
                    "position": {"x": 0, "y": 0.0},
                },
                {
                    "data": {"id": "0", "label": "T:1\nS:10"},
                    "classes": "status-active out-of-range",
                    "position": {"x": 300, "y": 30.0},
                },
                {
                    "data": {"id": "2", "label": "T:2\nS:11"},
                    "classes": "status-active",
                    "position": {"x": 600, "y": 60.0},
                },
                {
                    "data": {"id": "4", "label": "T:3\nS:12"},
                    "classes": "status-answer",
                    "position": {"x": 900, "y": 60.0},
                },
                {
                    "data": {
                        "id": "e-1_0",
                        "source": "-1",
                        "target": "0",
                        "action": "A",
                    }
                },
                {
                    "data": {
                        "id": "e0_2",
                        "source": "0",
                        "target": "2",
                        "action": "C",
                    }
                },
                {
                    "data": {
                        "id": "e2_4",
                        "source": "2",
                        "target": "4",
                        "action": "E",
                    }
                },
            ],
        )

    def test_node_detail_keeps_full_subtree_highlight(self) -> None:
        _, callbacks = self._callbacks()
        with patch.object(beam_app, "callback_context", SimpleNamespace(triggered=[])):
            result = callbacks["display_node"](
                {"id": "0"},
                False,
                None,
                "tab-detail",
                {"ts": 0},
            )

        self.assertEqual(result[1], "A")
        self.assertEqual(
            result[4][-4:],
            [
                {
                    "selector": 'node[id="2"],node[id="4"],node[id="3"]',
                    "style": {"border-width": "3px", "border-color": "#ff9800"},
                },
                {
                    "selector": 'edge[id="e0_3"],edge[id="e0_2"],edge[id="e2_4"]',
                    "style": {
                        "width": 3,
                        "line-color": "#ff9800",
                        "target-arrow-color": "#ff9800",
                    },
                },
                {
                    "selector": 'node[id="0"],node[id="-1"]',
                    "style": {"border-width": "3px", "border-color": "#ffeb3b"},
                },
                {
                    "selector": 'edge[id="e-1_0"]',
                    "style": {
                        "width": 4,
                        "line-color": "#ffeb3b",
                        "target-arrow-color": "#ffeb3b",
                    },
                },
            ],
        )

    def test_all_paths_graph_keeps_existing_segments(self) -> None:
        _, callbacks = self._callbacks()

        figure = callbacks["update_all_graph"](
            {"ts": 0},
            [2, 3],
            "tab-all-graph",
        )

        self.assertEqual(list(figure.data[0].x), [1, 2, None, 1, 2, None, 2, 3, None])
        self.assertEqual(
            list(figure.data[0].y),
            [10, 11, None, 10, 30, None, 11, 12, None],
        )

    def test_narrow_range_does_not_iterate_all_nodes(self) -> None:
        app, callbacks = self._callbacks()
        store = app._ahclib_beam_store

        class IndexedOnlyNodes(list):
            def __iter__(self):
                raise AssertionError("all nodes were scanned")

        nodes = store.processed["current_data"]["nodes"]
        store.processed["current_data"]["nodes"] = IndexedOnlyNodes(nodes)
        store.elements_cache.clear()

        with patch.object(beam_app, "callback_context", SimpleNamespace(triggered=[])):
            elements, _ = callbacks["update_elements"](
                {"ts": 0},
                [2, 3],
                [],
                [],
                [],
                0,
                "tab-tree",
                "LR",
                0,
                "",
                [],
            )
        figure = callbacks["update_all_graph"](
            {"ts": 0},
            [2, 3],
            "tab-all-graph",
        )

        self.assertEqual(len(elements), 7)
        self.assertEqual(len(figure.data[0].x), 9)

    def test_apps_do_not_share_history_or_cache(self) -> None:
        first_app, _ = self._callbacks()
        second_app, _ = self._callbacks()

        self.assertIsNot(
            first_app._ahclib_beam_store,
            second_app._ahclib_beam_store,
        )
        self.assertIsNot(
            first_app._ahclib_beam_store.elements_cache,
            second_app._ahclib_beam_store.elements_cache,
        )


class LRUCacheTest(unittest.TestCase):
    def test_cache_evicts_least_recently_used_entries(self) -> None:
        cache = LRUCache[str, list[int]](2, max_weight=3, get_weight=len)
        cache["a"] = [1]
        cache["b"] = [2]
        self.assertEqual(cache.get("a"), [1])

        cache["c"] = [3]

        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), [1])
        self.assertEqual(cache.get("c"), [3])


if __name__ == "__main__":
    unittest.main()
