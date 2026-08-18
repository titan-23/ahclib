import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from dash import Dash, html

from ahclib.vis import callbacks as vis_callbacks
from ahclib.vis.app import _register_visualizer_route
from ahclib.vis.callbacks import adjacent_case_id
from ahclib.vis.config import case_column_defs
from ahclib.vis.data import ResultStore, normalize_case_id
from ahclib.vis.layout import build_layout
from ahclib.main import get_args
from ahclib.vis.table_data import (
    build_case_rows,
    build_run_rows,
    parameter_column_specs,
    selected_row_ids,
)
from ahclib.vis.tabs import (
    TEXT_PREVIEW_HEAD,
    TEXT_PREVIEW_TAIL,
    _render_vis_tab,
    preview_text,
)


def _write_results(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as result_file:
        writer = csv.writer(result_file)
        writer.writerow(["filename", "score", "state", "time"])
        writer.writerows(rows)


def _find_component(component, component_id: str):
    if getattr(component, "id", None) == component_id:
        return component
    children = getattr(component, "children", None)
    if children is None:
        return None
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        found = _find_component(child, component_id)
        if found is not None:
            return found
    return None


class CallbackContextTest(unittest.TestCase):
    def test_triggered_property_id(self) -> None:
        callback_context = SimpleNamespace(
            triggered_prop_ids={"timestamp-table.cellClicked": "timestamp-table"}
        )
        with patch.object(vis_callbacks, "ctx", callback_context):
            self.assertEqual(
                vis_callbacks._triggered_property_id(),
                "timestamp-table.cellClicked",
            )

    def test_triggered_property_id_returns_none_without_trigger(self) -> None:
        callback_context = SimpleNamespace(triggered_prop_ids={})
        with patch.object(vis_callbacks, "ctx", callback_context):
            self.assertIsNone(vis_callbacks._triggered_property_id())


class ResultStoreTest(unittest.TestCase):
    def test_normalize_case_id_accepts_windows_and_posix_paths(self) -> None:
        self.assertEqual(normalize_case_id("./in/0000.txt"), "in/0000.txt")
        self.assertEqual(normalize_case_id(".\\in\\0000.txt"), "in/0000.txt")

    def test_long_frame_uses_stable_unique_case_ids_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            base_path = Path(temporary_dir)
            csv_path = base_path / "2026_01_01_00_00_00" / "result.csv"
            _write_results(
                csv_path,
                [
                    ("./group/case.txt", 10, "AC", 0.1),
                    ("./other/case.txt", 20, "AC", 0.2),
                    ("./group/case.txt", 30, "AC", 0.3),
                ],
            )
            store = ResultStore(base_path=str(base_path), direction="minimize")

            first = store.long_frame()
            first_version = store.version
            second = store.long_frame()

            self.assertIs(first, second)
            self.assertEqual(store.version, first_version)
            self.assertEqual(
                list(first["case_id"]),
                ["group/case.txt", "other/case.txt", "group/case.txt#1"],
            )
            self.assertEqual(list(first["name"]), ["case.txt"] * 3)

            _write_results(
                csv_path,
                [
                    ("./group/case.txt", 11, "AC", 0.1),
                    ("./other/case.txt", 20, "AC", 0.2),
                ],
            )
            updated = store.long_frame()
            self.assertGreater(store.version, first_version)
            self.assertEqual(list(updated["score"]), [11, 20])

    def test_meta_uses_parse_input_params_keys_and_detects_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_path = Path(temporary_dir)
            input_path = project_path / "in" / "a.txt"
            input_path.parent.mkdir()
            input_path.write_text("7 8\n", encoding="utf-8")
            (project_path / "ahc_settings.py").write_text(
                "class AHCSettings:\n"
                "    input_file_names = ['./in/a.txt']\n"
                "\n"
                "    @staticmethod\n"
                "    def parse_input_params(file_path):\n"
                "        with open(file_path, encoding='utf-8') as f:\n"
                "            n, m = map(int, f.readline().split())\n"
                "        return {'N': n, 'M': m}\n",
                encoding="utf-8",
            )

            previous_cwd = os.getcwd()
            previous_sys_path = list(sys.path)
            previous_module = sys.modules.pop("ahc_settings", None)
            try:
                os.chdir(project_path)
                store = ResultStore(
                    base_path=str(project_path / "results"),
                    direction="minimize",
                )
                first = store.meta()
                self.assertEqual(first.loc[0, "test_id"], "in/a.txt")
                self.assertEqual(first.loc[0, "N"], 7)
                self.assertEqual(first.loc[0, "M"], 8)

                input_path.write_text("11 12\n", encoding="utf-8")
                updated = store.meta()
                self.assertEqual(updated.loc[0, "N"], 11)
                self.assertEqual(updated.loc[0, "M"], 12)
            finally:
                os.chdir(previous_cwd)
                sys.path[:] = previous_sys_path
                sys.modules.pop("ahc_settings", None)
                if previous_module is not None:
                    sys.modules["ahc_settings"] = previous_module

    def test_delete_rejects_paths_outside_result_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            store = ResultStore(base_path=temporary_dir, direction="minimize")
            with self.assertRaises(ValueError):
                store.delete("../outside")

    def test_snapshot_reuses_one_version_and_precomputes_run_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_path = Path(temporary_dir)
            result_path = project_path / "results" / "run-1" / "result.csv"
            _write_results(
                result_path,
                [("./in/a.txt", 10, "AC", 0.1), ("./in/b.txt", 20, "TLE", 0.2)],
            )
            (project_path / "ahc_settings.py").write_text(
                "class AHCSettings:\n"
                "    @staticmethod\n"
                "    def get_score(scores):\n"
                "        return sum(scores)\n",
                encoding="utf-8",
            )

            previous_cwd = os.getcwd()
            previous_sys_path = list(sys.path)
            previous_module = sys.modules.pop("ahc_settings", None)
            try:
                os.chdir(project_path)
                store = ResultStore(
                    base_path=str(project_path / "results"),
                    direction="minimize",
                )
                first = store.snapshot()
                second = store.snapshot()
                summary = first.run_summary.iloc[0]

                self.assertIs(first, second)
                self.assertEqual(summary["aggregate_score"], 30)
                self.assertEqual(summary["average_score"], 15)
                self.assertEqual(summary["median_score"], 15)
                self.assertEqual(summary["ng_cnt"], 1)
                self.assertAlmostEqual(summary["ci95_score"], 9.8)

                _write_results(
                    result_path,
                    [("./in/a.txt", 11, "AC", 0.1)],
                )
                updated = store.snapshot()
                self.assertGreater(updated.version, first.version)
                self.assertEqual(updated.run_summary.iloc[0]["aggregate_score"], 11)
            finally:
                os.chdir(previous_cwd)
                sys.path[:] = previous_sys_path
                sys.modules.pop("ahc_settings", None)
                if previous_module is not None:
                    sys.modules["ahc_settings"] = previous_module

    def test_meta_reparses_only_changed_inputs_and_exposes_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            project_path = Path(temporary_dir)
            input_dir = project_path / "in"
            input_dir.mkdir()
            first_input = input_dir / "a.txt"
            second_input = input_dir / "b.txt"
            first_input.write_text("1\n", encoding="utf-8")
            second_input.write_text("2\n", encoding="utf-8")
            (project_path / "ahc_settings.py").write_text(
                "CALLS = 0\n"
                "class AHCSettings:\n"
                "    input_file_names = ['./in/a.txt', './in/b.txt']\n"
                "    @staticmethod\n"
                "    def parse_input_params(path):\n"
                "        global CALLS\n"
                "        CALLS += 1\n"
                "        with open(path, encoding='utf-8') as f:\n"
                "            value = int(f.read())\n"
                "        if value < 0:\n"
                "            raise ValueError('negative')\n"
                "        return {'N': value}\n",
                encoding="utf-8",
            )

            previous_cwd = os.getcwd()
            previous_sys_path = list(sys.path)
            previous_module = sys.modules.pop("ahc_settings", None)
            try:
                os.chdir(project_path)
                store = ResultStore(
                    base_path=str(project_path / "results"),
                    direction="minimize",
                )
                store.snapshot()
                import ahc_settings

                self.assertEqual(ahc_settings.CALLS, 2)
                first_input.write_text("-10\n", encoding="utf-8")
                updated = store.snapshot()
                self.assertEqual(ahc_settings.CALLS, 3)
                self.assertTrue(
                    any(
                        "parse_input_params の失敗" in item for item in updated.warnings
                    )
                )
            finally:
                os.chdir(previous_cwd)
                sys.path[:] = previous_sys_path
                sys.modules.pop("ahc_settings", None)
                if previous_module is not None:
                    sys.modules["ahc_settings"] = previous_module

    def test_annotations_are_separate_and_read_only_mode_rejects_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            run_path = Path(temporary_dir) / "run-1"
            run_path.mkdir()
            store = ResultStore(base_path=temporary_dir, direction="minimize")

            store.save_tag("run-1", "fast")
            store.save_memo("run-1", "first")
            store.toggle_favorite("run-1")
            store.save_case_memo("run-1", "in/a.txt", "check")
            store.toggle_case_bookmark("run-1", "in/a.txt")

            self.assertEqual(store.get_tag("run-1"), "fast")
            self.assertTrue(store.is_favorite("run-1"))
            run_annotations = store.run_annotations(["run-1"])["run-1"]
            self.assertEqual(run_annotations["memo"], "first")
            self.assertEqual(run_annotations["tag"], "fast")
            self.assertEqual(
                store.case_annotations("run-1")["in/a.txt"],
                {"memo": "check", "bookmark": True},
            )
            self.assertTrue((run_path / ".ahclib_vis.json").exists())

            read_only_store = ResultStore(
                base_path=temporary_dir,
                direction="minimize",
                read_only=True,
            )
            with self.assertRaises(PermissionError):
                read_only_store.save_tag("run-1", "blocked")
            with self.assertRaises(PermissionError):
                read_only_store.delete("run-1")
            self.assertTrue(run_path.exists())


class TableDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.results = pd.DataFrame(
            [
                {
                    "timestamp": "run-1",
                    "case_id": "in/a.txt",
                    "test_id": "in/a.txt",
                    "filename": "./in/a.txt",
                    "name": "a.txt",
                    "score": 10,
                    "state": "AC",
                    "time": 1.0,
                },
                {
                    "timestamp": "run-1",
                    "case_id": "in/b.txt",
                    "test_id": "in/b.txt",
                    "filename": "./in/b.txt",
                    "name": "b.txt",
                    "score": 0,
                    "state": "AC",
                    "time": 2.0,
                },
                {
                    "timestamp": "run-2",
                    "case_id": "in/a.txt",
                    "test_id": "in/a.txt",
                    "filename": "./in/a.txt",
                    "name": "a.txt",
                    "score": 8,
                    "state": "AC",
                    "time": 0.8,
                },
                {
                    "timestamp": "run-2",
                    "case_id": "in/b.txt",
                    "test_id": "in/b.txt",
                    "filename": "./in/b.txt",
                    "name": "b.txt",
                    "score": 5,
                    "state": "TLE",
                    "time": 3.0,
                },
            ]
        )

    def test_case_rows_include_base_differences_and_stable_ids(self) -> None:
        rows = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
        )
        by_id = {row["id"]: row for row in rows}

        self.assertEqual(by_id["in/a.txt"]["score_delta"], -2)
        self.assertAlmostEqual(by_id["in/a.txt"]["time_delta"], -0.2)
        self.assertEqual(by_id["in/a.txt"]["rel"], 0.8)
        self.assertEqual(by_id["in/a.txt"]["comparison"], "改善")
        self.assertEqual(by_id["in/a.txt"]["abs_score_delta"], 2)
        self.assertIsNone(by_id["in/b.txt"]["rel"])
        self.assertEqual(by_id["in/b.txt"]["comparison"], "TLE")
        self.assertEqual(len(by_id), len(rows))

        sorted_rows = sorted(rows, key=lambda row: row["score"], reverse=True)
        self.assertEqual(sorted_rows[0]["id"], "in/a.txt")
        self.assertEqual(by_id[sorted_rows[0]["id"]]["name"], "a.txt")

    def test_case_rows_can_filter_non_accepted_cases(self) -> None:
        rows = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            non_accepted_only=True,
        )
        self.assertEqual([row["id"] for row in rows], ["in/b.txt"])

        rows_without_state = build_case_rows(
            self.results.drop(columns="state"),
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            non_accepted_only=True,
        )
        self.assertEqual(rows_without_state, [])

    def test_case_rows_can_filter_comparison_categories(self) -> None:
        improved = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            comparison_filters=["improved"],
        )
        failed = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            comparison_filters=["failed"],
        )
        self.assertEqual([row["id"] for row in improved], ["in/a.txt"])
        self.assertEqual([row["id"] for row in failed], ["in/b.txt"])

        bookmarked = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            comparison_filters=["bookmarked"],
            annotations={"in/b.txt": {"bookmark": True, "memo": "inspect"}},
        )
        self.assertEqual([row["id"] for row in bookmarked], ["in/b.txt"])
        self.assertEqual(bookmarked[0]["case_memo"], "inspect")

    def test_case_rows_include_input_parameters(self) -> None:
        metadata = pd.DataFrame(
            [
                {"test_id": "in/a.txt", "N": 10, "category": "small"},
                {"test_id": "in/b.txt", "N": 20, "category": "large"},
            ]
        )
        rows = build_case_rows(
            self.results,
            target_timestamp="run-2",
            base_timestamp="run-1",
            direction="minimize",
            metadata=metadata,
        )
        by_id = {row["id"]: row for row in rows}

        self.assertEqual(by_id["in/a.txt"]["__parameter_0"], 10)
        self.assertEqual(by_id["in/b.txt"]["__parameter_1"], "large")

        specs = parameter_column_specs(metadata)
        columns = {
            column["field"]: column for column in case_column_defs("minimize", specs)
        }
        self.assertIn("base_rank", columns)
        self.assertIn("base_time", columns)
        self.assertEqual(columns["__parameter_0"]["filter"], "agNumberColumnFilter")
        self.assertEqual(
            columns["__parameter_1"]["filter"],
            "agTextColumnFilter",
        )

    def test_run_rows_keep_unavailable_relative_scores_empty(self) -> None:
        rows, actual_base = build_run_rows(
            self.results,
            base_timestamp="run-1",
            memo_getter=lambda _timestamp: "",
        )
        by_id = {row["id"]: row for row in rows}

        self.assertEqual(actual_base, "run-1")
        self.assertEqual(by_id["run-2"]["rel_geo"], 0.8)
        self.assertEqual(by_id["run-2"]["rel_missing"], 1)
        self.assertEqual(by_id["run-2"]["ng_cnt"], 1)

        annotated_rows, _ = build_run_rows(
            self.results,
            base_timestamp="run-1",
            memo_getter=lambda _timestamp: "",
            tag_getter=lambda timestamp: "new" if timestamp == "run-2" else "",
            favorite_getter=lambda timestamp: timestamp == "run-2",
        )
        annotated_by_id = {row["id"]: row for row in annotated_rows}
        self.assertEqual(annotated_by_id["run-2"]["tag"], "new")
        self.assertEqual(annotated_by_id["run-2"]["favorite_str"], "★")

    def test_selected_row_ids_do_not_depend_on_display_order(self) -> None:
        selected_rows = [
            {"id": "in/b.txt", "score": 5},
            {"id": "in/a.txt", "score": 8},
        ]
        self.assertEqual(
            selected_row_ids(selected_rows),
            ["in/b.txt", "in/a.txt"],
        )
        self.assertEqual(
            selected_row_ids({"ids": ["run-2", "run-1"]}),
            ["run-2", "run-1"],
        )

    def test_adjacent_case_uses_filtered_and_sorted_display_order(self) -> None:
        visible_rows = [{"id": "case-c"}, {"id": "case-a"}]
        self.assertEqual(
            adjacent_case_id(visible_rows, {"ids": ["case-c"]}, 1),
            "case-a",
        )
        self.assertEqual(
            adjacent_case_id(visible_rows, {"ids": ["case-a"]}, -1),
            "case-c",
        )


class GridLayoutTest(unittest.TestCase):
    def test_grids_use_application_row_ids_and_filters(self) -> None:
        layout = build_layout("minimize")
        run_grid = _find_component(layout, "timestamp-table")
        case_grid = _find_component(layout, "file-name-table")

        self.assertIsNotNone(run_grid)
        self.assertIsNotNone(case_grid)
        self.assertIsNone(_find_component(layout, "graph-reset"))
        self.assertEqual(run_grid.getRowId, "params.data.id")
        self.assertEqual(case_grid.getRowId, "params.data.id")
        self.assertEqual(
            run_grid.dashGridOptions["rowSelection"]["mode"],
            "multiRow",
        )
        self.assertEqual(
            case_grid.dashGridOptions["rowSelection"]["mode"],
            "singleRow",
        )
        self.assertTrue(case_grid.defaultColDef["floatingFilter"])
        self.assertIn("cellKeyDown", case_grid.eventListeners)
        self.assertIn("columnState", case_grid.persisted_props)

        detail_card = _find_component(layout, "detail-card")
        self.assertEqual(detail_card.style["minHeight"], "600px")

        run_fields = [column["field"] for column in run_grid.columnDefs]
        total_index = run_fields.index("aggregate_score")
        self.assertNotIn("favorite_str", run_fields)
        self.assertNotIn("average_score", run_fields)
        self.assertEqual(run_fields[total_index + 1], "rel_geo")
        self.assertEqual(run_grid.defaultColDef["minWidth"], 48)
        self.assertTrue(all("width" in column for column in run_grid.columnDefs))
        self.assertEqual(
            run_grid.columnDefs[total_index]["valueFormatter"]["function"],
            "params.value == null ? '' : d3.format(',.12~f')(params.value)",
        )

    def test_read_only_layout_disables_edit_and_delete_columns(self) -> None:
        layout = build_layout("minimize", read_only=True)
        run_grid = _find_component(layout, "timestamp-table")
        case_grid = _find_component(layout, "file-name-table")
        run_columns = {column["field"]: column for column in run_grid.columnDefs}
        case_columns = {column["field"]: column for column in case_grid.columnDefs}

        self.assertNotIn("delete_btn", run_columns)
        self.assertFalse(run_columns["memo"]["editable"])
        self.assertFalse(run_columns["tag"]["editable"])
        self.assertFalse(case_columns["case_memo"]["editable"])

    def test_vis_command_accepts_private_read_only_sharing_options(self) -> None:
        args = get_args(["vis", "--tailscale", "--port", "9000"])
        self.assertTrue(args.tailscale)
        self.assertEqual(args.port, 9000)


class DetailContentTest(unittest.TestCase):
    def test_large_text_uses_head_and_tail_preview_without_download(self) -> None:
        content = "a" * 250_000
        shown, omitted = preview_text(content)
        full, full_omitted = preview_text(content, full=True)

        self.assertEqual(omitted, 250_000 - TEXT_PREVIEW_HEAD - TEXT_PREVIEW_TAIL)
        self.assertLess(len(shown), len(content))
        self.assertEqual(full, content)
        self.assertEqual(full_omitted, 0)

    def test_visualizer_route_is_lazy_and_sandbox_headers_are_set(self) -> None:
        iframe = _render_vis_tab("run-1", "in/a.txt")
        self.assertEqual(iframe.sandbox, "allow-scripts")
        self.assertIsNone(getattr(iframe, "srcDoc", None))

        with tempfile.TemporaryDirectory() as temporary_dir:
            project_path = Path(temporary_dir)
            _write_results(
                project_path / "results" / "run-1" / "result.csv",
                [("./in/a.txt", 10, "AC", 0.1)],
            )
            input_path = project_path / "in" / "a.txt"
            input_path.parent.mkdir()
            input_path.write_text("</script> input", encoding="utf-8")
            output_path = project_path / "results" / "run-1" / "out" / "a.txt"
            output_path.parent.mkdir()
            output_path.write_text("answer", encoding="utf-8")
            visualizer_path = project_path / "visualizer.html"
            visualizer_path.write_text(
                "<html><body>vis</body></html>", encoding="utf-8"
            )

            previous_cwd = os.getcwd()
            try:
                os.chdir(project_path)
                store = ResultStore(
                    base_path=str(project_path / "results"),
                    direction="minimize",
                )
                app = Dash(__name__)
                app.layout = html.Div()
                _register_visualizer_route(app, store)
                response = app.server.test_client().get(
                    "/_ahclib_visualizer?timestamp=run-1&case_id=in%2Fa.txt"
                )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn(
                "default-src 'none'", response.headers["Content-Security-Policy"]
            )
            self.assertNotIn(b"</script> input", response.data)
            self.assertIn(b"answer", response.data)


if __name__ == "__main__":
    unittest.main()
