import multiprocessing
import os
import sys
from datetime import datetime

def _run_test_process():
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        from ahc_settings import AHCSettings
        from ahclib.parallel_tester import run_test
        njobs = min(AHCSettings.njobs, multiprocessing.cpu_count() - 1)
        run_test(AHCSettings, njobs, verbose=False, compile=True, record=True)
    except Exception as e:
        print(f"Error in test process: {e}")

def _run_opt_process():
    try:
        if os.getcwd() not in sys.path:
            sys.path.append(os.getcwd())
        from ahc_settings import AHCSettings
        from ahclib.optimizer import run_optimizer
        run_optimizer(AHCSettings, sampler=None, pruner="WilcoxonPruner")
    except Exception as e:
        print(f"Error in opt process: {e}")

class TaskManager:
    """ GUIからのタスク実行をキューで管理するクラス """
    def __init__(self):
        self.process = None
        self.current_task = None
        self.queue = []  # {"type": "test"|"opt", "time": "18:24:25"}

    def add_test(self):
        self.queue.append({"type": "test", "time": datetime.now().strftime("%H:%M:%S")})
        self._check_queue()

    def add_opt(self):
        self.queue.append({"type": "opt", "time": datetime.now().strftime("%H:%M:%S")})
        self._check_queue()

    def _check_queue(self):
        # 現在のプロセスが終わっているかチェック
        if self.process is not None:
            if self.process.is_alive():
                return
            else:
                self.process = None
                self.current_task = None
        
        # キューにタスクがあれば実行
        if self.queue and self.process is None:
            self.current_task = self.queue.pop(0)
            target = _run_test_process if self.current_task["type"] == "test" else _run_opt_process
            self.process = multiprocessing.Process(target=target)
            self.process.start()

    def stop_current(self):
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=1)
            if self.process.is_alive():
                self.process.kill()
        self.process = None
        self.current_task = None
        self._check_queue()  # 次のタスクがあれば開始する

    def clear_queue(self):
        self.queue.clear()

    def get_queue_status(self):
        self._check_queue() # 状態を最新化
        return {
            "current": self.current_task,
            "queue": self.queue
        }

# シングルトンとしてエクスポート
task_manager = TaskManager()
