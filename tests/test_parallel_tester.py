import collections
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ahclib import parallel_tester
from ahclib.main import get_args, resolve_cpu_affinity
from ahclib.parallel_tester import ParallelTester


class CpuAffinityTest(unittest.TestCase):
    def test_cli_flag_is_optional_for_test_and_opt(self) -> None:
        self.assertIsNone(get_args(["test"]).cpu_affinity)
        self.assertTrue(get_args(["test", "--cpu-affinity"]).cpu_affinity)
        self.assertFalse(get_args(["test", "--no-cpu-affinity"]).cpu_affinity)
        self.assertIsNone(get_args(["opt"]).cpu_affinity)
        self.assertTrue(get_args(["opt", "--cpu-affinity"]).cpu_affinity)
        self.assertFalse(get_args(["opt", "--no-cpu-affinity"]).cpu_affinity)

    def test_settings_value_is_used_when_cli_flag_is_omitted(self) -> None:
        class EnabledSettings:
            cpu_affinity = True

        class LegacySettings:
            pass

        self.assertTrue(resolve_cpu_affinity(None, EnabledSettings))
        self.assertFalse(resolve_cpu_affinity(False, EnabledSettings))
        self.assertTrue(resolve_cpu_affinity(True, LegacySettings))
        self.assertFalse(resolve_cpu_affinity(None, LegacySettings))

    def test_cpu_selection_reserves_lowest_available_cpu(self) -> None:
        with (
            mock.patch.object(parallel_tester.os, "name", "posix"),
            mock.patch.object(
                parallel_tester.os,
                "sched_getaffinity",
                return_value={2, 4, 6, 8},
                create=True,
            ),
            mock.patch.object(parallel_tester.shutil, "which", return_value="/usr/bin/taskset"),
        ):
            self.assertEqual(parallel_tester.get_cpu_affinity_ids(2), (4, 6))
            self.assertEqual(parallel_tester.get_cpu_affinity_ids(100), (4, 6, 8))

    def test_single_available_cpu_is_used(self) -> None:
        with (
            mock.patch.object(parallel_tester.os, "name", "posix"),
            mock.patch.object(
                parallel_tester.os,
                "sched_getaffinity",
                return_value={5},
                create=True,
            ),
            mock.patch.object(parallel_tester.shutil, "which", return_value="/usr/bin/taskset"),
        ):
            self.assertEqual(parallel_tester.get_cpu_affinity_ids(10), (5,))

    def test_unsupported_environment_reports_an_error(self) -> None:
        with mock.patch.object(parallel_tester.os, "name", "nt"):
            with self.assertRaisesRegex(RuntimeError, "Linux"):
                parallel_tester.get_cpu_affinity_ids(1)

    def test_missing_taskset_reports_an_error(self) -> None:
        with (
            mock.patch.object(parallel_tester.os, "name", "posix"),
            mock.patch.object(
                parallel_tester.os,
                "sched_getaffinity",
                return_value={0, 1},
                create=True,
            ),
            mock.patch.object(parallel_tester.shutil, "which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "taskset"):
                parallel_tester.get_cpu_affinity_ids(1)

    def test_solver_command_is_wrapped_with_taskset(self) -> None:
        self.assertEqual(
            parallel_tester._command_with_cpu_affinity(["./a.out", "10"], 3),
            ["taskset", "--cpu-list", "3", "./a.out", "10"],
        )
        command = ["./a.out"]
        self.assertIs(parallel_tester._command_with_cpu_affinity(command, None), command)

    def test_execute_solver_uses_wrapped_command(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="output", stderr="Score = 10\n")
        with tempfile.TemporaryDirectory() as temporary_dir:
            input_path = Path(temporary_dir) / "0000.txt"
            input_path.write_text("input", encoding="utf-8")
            with mock.patch.object(parallel_tester.subprocess, "run", return_value=completed) as run:
                result = parallel_tester._execute_solver(str(input_path), ["./a.out"], None, True, cpu_id=7)

        self.assertEqual(result[0], "AC")
        self.assertEqual(result[1], 10)
        self.assertEqual(
            run.call_args.args[0],
            ["taskset", "--cpu-list", "7", "./a.out"],
        )
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)

    def test_execute_solver_discards_stdout_when_not_recording(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=None, stderr="Score = 10\n")
        with tempfile.TemporaryDirectory() as temporary_dir:
            input_path = Path(temporary_dir) / "0000.txt"
            input_path.write_text("input", encoding="utf-8")
            with mock.patch.object(parallel_tester.subprocess, "run", return_value=completed) as run:
                result = parallel_tester._execute_solver(
                    str(input_path),
                    ["./a.out"],
                    None,
                    True,
                    capture_stdout=False,
                )

        self.assertEqual(result[0], "AC")
        self.assertEqual(result[2], "")
        self.assertEqual(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.PIPE)

    def test_optuna_discards_stdout(self) -> None:
        solver_result = ("AC", 10, "", "Score = 10\n", 0.1)
        with mock.patch.object(parallel_tester, "_execute_solver", return_value=solver_result) as execute_solver:
            score = parallel_tester._run_case_for_opt(
                "0000.txt",
                ["./a.out"],
                None,
                True,
                False,
                {},
            )

        self.assertEqual(score, 10)
        self.assertFalse(execute_solver.call_args.kwargs["capture_stdout"])

        with mock.patch.object(
            parallel_tester,
            "_execute_solver_cancellable",
            return_value=solver_result,
        ) as execute_solver_cancellable:
            score = parallel_tester._run_case_for_opt(
                "0000.txt",
                ["./a.out"],
                None,
                True,
                False,
                {},
                cancel_event=threading.Event(),
            )

        self.assertEqual(score, 10)
        self.assertFalse(execute_solver_cancellable.call_args.kwargs["capture_stdout"])

    def test_worker_discards_stdout_when_not_recording(self) -> None:
        solver_result = ("AC", 10, "", "Score = 10\n", 0.1)
        config = mock.Mock(command=["./a.out"], timeout=None, is_int=True, record=False)
        expected = ("0000.txt", 10, 1.0, "AC", "0.100")
        with (
            mock.patch.object(parallel_tester, "_execute_solver", return_value=solver_result) as execute_solver,
            mock.patch.object(parallel_tester, "_handle_ac_case", return_value=expected),
        ):
            result = parallel_tester._worker_process_file(("0000.txt", config, mock.sentinel.state, None, None))

        self.assertEqual(result, expected)
        self.assertFalse(execute_solver.call_args.kwargs["capture_stdout"])

    def test_parallel_map_keeps_one_case_per_cpu(self) -> None:
        tester = object.__new__(ParallelTester)
        tester.cpu_count = 2
        tester.cpu_ids = (2, 4)
        tester.cpu_locks = {}

        state_lock = threading.Lock()
        active = collections.Counter()
        maximum_active = collections.Counter()

        def worker(arguments):
            case_index, cpu_id, _cpu_lock = arguments
            with state_lock:
                active[cpu_id] += 1
                maximum_active[cpu_id] = max(maximum_active[cpu_id], active[cpu_id])
            time.sleep(0.01)
            with state_lock:
                active[cpu_id] -= 1
            return case_index, cpu_id

        results = tester._map_in_parallel(worker, [(case_index,) for case_index in range(8)])

        self.assertEqual(
            results,
            [
                (0, 2),
                (1, 4),
                (2, 2),
                (3, 4),
                (4, 2),
                (5, 4),
                (6, 2),
                (7, 4),
            ],
        )
        self.assertEqual(maximum_active, {2: 1, 4: 1})

    def test_case_to_cpu_mapping_does_not_depend_on_execution_order(self) -> None:
        tester = object.__new__(ParallelTester)
        tester.cpu_ids = (1, 3, 5)
        tester.cpu_locks = {}

        first = {i: tester._cpu_target(i)[0] for i in range(9)}
        second = {i: tester._cpu_target(i)[0] for i in (8, 2, 5, 1, 7, 0, 6, 4, 3)}

        self.assertEqual(first, second)

    def test_optuna_shuffle_keeps_original_case_to_cpu_mapping(self) -> None:
        tester = object.__new__(ParallelTester)
        tester.input_file_names = [f"./in/{i:04d}.txt" for i in range(8)]
        tester.optuna_seed = 10
        tester.execute_command = ["./a.out"]
        tester.added_command = []
        tester.timeout = None
        tester.is_int = True
        tester.use_relative_score = False
        tester.pre_data = {}
        tester.cpu_count = 2
        tester.cpu_ids = (2, 4)
        tester.cpu_locks = {}

        class Trial:
            number = 3

            def report(self, _score, _step) -> None:
                return None

            def should_prune(self) -> bool:
                return False

        def worker(arguments):
            case_index = arguments[1]
            cpu_id = arguments[-2]
            return case_index, float(cpu_id)

        with mock.patch.object(
            parallel_tester,
            "_worker_process_file_opt_pruner",
            side_effect=worker,
        ):
            result = tester.run_opt_pruner(Trial())

        self.assertFalse(result.pruned)
        self.assertEqual(result.scores, [2.0, 4.0, 2.0, 4.0, 2.0, 4.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
