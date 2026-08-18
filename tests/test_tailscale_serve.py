import unittest
from typing import Optional
from unittest.mock import patch

from ahclib.tailscale_serve import (
    TailscaleServe,
    _extract_private_url,
    _find_tailscale_executable,
)


class _FakeProcess:
    def __init__(
        self,
        output: list[str],
        return_code: Optional[int] = None,
    ) -> None:
        self.stdout = iter(output)
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def poll(self) -> Optional[int]:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        return self.return_code

    def kill(self) -> None:
        self.killed = True
        self.return_code = -9


class TailscaleServeTest(unittest.TestCase):
    def test_extract_private_url(self) -> None:
        self.assertEqual(
            _extract_private_url(
                "Available within your tailnet: "
                "https://contest-pc.example-tailnet.ts.net"
            ),
            "https://contest-pc.example-tailnet.ts.net",
        )
        self.assertEqual(
            _extract_private_url("https://contest-pc.example.ts.net:8443/"),
            "https://contest-pc.example.ts.net:8443",
        )
        self.assertIsNone(_extract_private_url("https://example.com"))

    def test_start_uses_foreground_serve_and_returns_private_url(self) -> None:
        process = _FakeProcess(
            [
                "Available within your tailnet:\n",
                "https://contest-pc.example-tailnet.ts.net\n",
                "Press Ctrl+C to exit.\n",
            ]
        )
        target = "http://127.0.0.1:8080"

        with patch(
            "ahclib.tailscale_serve._find_tailscale_executable",
            return_value="tailscale",
        ), patch(
            "ahclib.tailscale_serve.subprocess.Popen",
            return_value=process,
        ) as popen:
            serve = TailscaleServe.start(target, startup_timeout=1)

        self.assertEqual(
            serve.private_url,
            "https://contest-pc.example-tailnet.ts.net",
        )
        command = popen.call_args.args[0]
        self.assertEqual(command, ["tailscale", "serve", target])
        self.assertNotIn("funnel", command)
        self.assertNotIn("--bg", command)

        serve.stop()
        self.assertTrue(process.terminated)

    def test_start_reports_when_serve_fails(self) -> None:
        process = _FakeProcess(["Serve is not enabled\n"], return_code=1)

        with self.assertLogs("ahclib.tailscale_serve", level="INFO") as logs:
            with patch(
                "ahclib.tailscale_serve._find_tailscale_executable",
                return_value="tailscale",
            ), patch(
                "ahclib.tailscale_serve.subprocess.Popen",
                return_value=process,
            ):
                with self.assertRaisesRegex(RuntimeError, "failed to start"):
                    TailscaleServe.start("http://127.0.0.1:8080", startup_timeout=1)

        self.assertIn(
            "INFO:ahclib.tailscale_serve:" "- tailscale     : Serve is not enabled",
            logs.output,
        )

    def test_start_terminates_unconfirmed_foreground_process(self) -> None:
        process = _FakeProcess([])

        with patch(
            "ahclib.tailscale_serve._find_tailscale_executable",
            return_value="tailscale",
        ), patch(
            "ahclib.tailscale_serve.subprocess.Popen",
            return_value=process,
        ):
            with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                TailscaleServe.start("http://127.0.0.1:8080", startup_timeout=1)

        self.assertTrue(process.terminated)

    def test_find_executable_reports_missing_installation(self) -> None:
        with patch("ahclib.tailscale_serve.shutil.which", return_value=None), patch(
            "ahclib.tailscale_serve.os.name", "posix"
        ):
            with self.assertRaisesRegex(RuntimeError, "CLI was not found"):
                _find_tailscale_executable()


if __name__ == "__main__":
    unittest.main()
