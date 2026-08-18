from __future__ import annotations

import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)

TAILSCALE_SERVE_STARTUP_TIMEOUT_SEC = 120
TAILSCALE_PRIVATE_URL_PATTERN = re.compile(
    r"https://[A-Za-z0-9][A-Za-z0-9.-]*\.ts\.net(?::\d+)?"
)


def _find_tailscale_executable() -> str:
    executable = shutil.which("tailscale")
    if executable is not None:
        return executable

    if os.name == "nt":
        program_files = os.getenv("ProgramFiles")
        if program_files:
            windows_executable = os.path.join(
                program_files, "Tailscale", "tailscale.exe"
            )
            if os.path.isfile(windows_executable):
                return windows_executable

    raise RuntimeError(
        "Tailscale CLI was not found. Install Tailscale in the same environment "
        "where ahclib runs, sign in, and try again."
    )


def _extract_private_url(line: str) -> Optional[str]:
    match = TAILSCALE_PRIVATE_URL_PATTERN.search(line)
    return match.group(0) if match is not None else None


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclass
class TailscaleServe:
    """ahclib と同時に終了する Tailscale Serve の実行状態"""

    process: subprocess.Popen[str]
    private_url: str

    @classmethod
    def start(
        cls,
        target: str,
        startup_timeout: float = TAILSCALE_SERVE_STARTUP_TIMEOUT_SEC,
    ) -> TailscaleServe:
        executable = _find_tailscale_executable()
        process = subprocess.Popen(
            [executable, "serve", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        output_lines: queue.Queue[Optional[str]] = queue.Queue()
        startup_finished = threading.Event()

        def _read_output() -> None:
            assert process.stdout is not None
            for raw_line in process.stdout:
                if not startup_finished.is_set():
                    output_lines.put(raw_line.rstrip())
            if not startup_finished.is_set():
                output_lines.put(None)

        threading.Thread(target=_read_output, daemon=True).start()
        startup_messages: list[str] = []

        try:
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                try:
                    line = output_lines.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue

                if line is None:
                    break
                if not line:
                    continue

                startup_messages.append(line)
                private_url = _extract_private_url(line)
                if private_url is not None:
                    return cls(process=process, private_url=private_url)

                # 初回は HTTPS を有効にするための確認 URL が表示される
                logger.info("- tailscale     : %s", line)

            recent_output = "\n".join(startup_messages[-10:]) or "no output"
            if process.poll() is None:
                raise RuntimeError(
                    "Tailscale Serve startup was not confirmed within "
                    f"{startup_timeout:g} seconds. Follow any consent URL above "
                    "and try again.\n"
                    f"Tailscale output:\n{recent_output}"
                )
            raise RuntimeError(f"Tailscale Serve failed to start:\n{recent_output}")
        except BaseException:
            _stop_process(process)
            raise
        finally:
            startup_finished.set()

    def stop(self) -> None:
        _stop_process(self.process)
        logger.info("- remote access : Tailscale Serve stopped")
