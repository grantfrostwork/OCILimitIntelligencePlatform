from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class OciCliError(RuntimeError):
    def __init__(self, command: list[str], returncode: int, stderr: str, stdout: str = "") -> None:
        super().__init__(stderr.strip() or stdout.strip() or f"OCI CLI failed with {returncode}")
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


@dataclass
class OciCli:
    settings: Settings

    def base_args(self, region: str | None = None) -> list[str]:
        args = [self.settings.oci_cli_path]
        if self.settings.oci_auth_mode == "instance_principal":
            args.extend(["--auth", "instance_principal"])
        else:
            args.extend(["--profile", self.settings.oci_profile])
        if region:
            args.extend(["--region", region])
        args.extend(
            [
                "--connection-timeout",
                "10",
                "--read-timeout",
                str(self.settings.oci_command_timeout_seconds),
                "--output",
                "json",
            ]
        )
        return args

    def run(self, args: list[str], region: str | None = None) -> dict[str, Any]:
        command = self.base_args(region=region) + args
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.settings.oci_command_timeout_seconds + 10,
            )
        except subprocess.TimeoutExpired as exc:
            raise OciCliError(command, 124, f"Command timed out after {exc.timeout}s") from exc

        if completed.returncode != 0:
            raise OciCliError(command, completed.returncode, completed.stderr, completed.stdout)

        if not completed.stdout.strip():
            return {}

        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OciCliError(command, completed.returncode, "OCI CLI returned invalid JSON", completed.stdout) from exc

    def is_not_found_or_unsupported(self, exc: OciCliError) -> bool:
        text = f"{exc.stderr}\n{exc.stdout}\n{exc}".lower()
        return "404" in text or "not found" in text or "notavailable" in text
