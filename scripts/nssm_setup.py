"""NSSM Windows service wrapper for Astridr.

Installs, manages, and removes the Astridr framework as a Windows service
using NSSM (Non-Sucking Service Manager).

Usage:
    python scripts/nssm_setup.py install
    python scripts/nssm_setup.py start
    python scripts/nssm_setup.py stop
    python scripts/nssm_setup.py restart
    python scripts/nssm_setup.py status
    python scripts/nssm_setup.py uninstall
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Default service configuration
SERVICE_NAME = "Astridr"
LOG_ROTATE_BYTES = 10_000_000  # 10 MB


class NSSMError(Exception):
    """Raised when an NSSM operation fails."""


class NSSMService:
    """Manages the Astridr Windows service via NSSM."""

    SERVICE_NAME = SERVICE_NAME

    def __init__(self, nssm_path: str = "nssm.exe") -> None:
        self.nssm = nssm_path
        self.project_root = Path(__file__).resolve().parent.parent
        self.logs_dir = self.project_root / "logs"

    def install(self) -> None:
        """Install Astridr as a Windows service.

        Configures:
        - Python executable running ``-m astridr``
        - Working directory set to project root
        - Stdout/stderr logging with rotation
        - Auto-start on boot
        - Restart on failure with 5-second delay
        """
        python = sys.executable
        logger.info(
            "nssm.installing",
            service=self.SERVICE_NAME,
            python=python,
            project_root=str(self.project_root),
        )

        # Ensure logs directory exists
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Install the service
        self._run_nssm(
            ["install", self.SERVICE_NAME, python, "-m", "astridr"]
        )

        # Configure service parameters
        self._set("AppDirectory", str(self.project_root))
        self._set("AppStdout", str(self.logs_dir / "astridr-stdout.log"))
        self._set("AppStderr", str(self.logs_dir / "astridr-stderr.log"))
        self._set("AppRotateFiles", "1")
        self._set("AppRotateBytes", str(LOG_ROTATE_BYTES))
        self._set("AppStdoutCreationDisposition", "4")  # Append
        self._set("AppStderrCreationDisposition", "4")  # Append
        self._set("Start", "SERVICE_AUTO_START")

        # Restart on failure — up to 3 times with 5-second delay
        self._set("AppExit", "Default", "Restart")
        self._set("AppRestartDelay", "5000")

        # Graceful stop: send Ctrl+C first, wait 5s, then escalate
        self._set("AppStopMethodSkip", "0")
        self._set("AppStopMethodConsole", "5000")
        self._set("AppStopMethodWindow", "5000")
        self._set("AppStopMethodThreads", "5000")

        # Pass through Supabase environment variables
        self._set(
            "AppEnvironmentExtra",
            "SUPABASE_URL=http://localhost:54321",
            "SUPABASE_SERVICE_ROLE_KEY=%SUPABASE_SERVICE_ROLE_KEY%",
        )

        # Description
        self._set("Description", "Astridr AI Agent Framework")
        self._set("DisplayName", "Astridr Agent")

        logger.info("nssm.installed", service=self.SERVICE_NAME)

    def uninstall(self) -> None:
        """Remove the Astridr Windows service."""
        logger.info("nssm.uninstalling", service=self.SERVICE_NAME)
        # Stop first if running (ignore errors)
        try:
            self.stop()
        except NSSMError:
            pass
        self._run_nssm(["remove", self.SERVICE_NAME, "confirm"])
        logger.info("nssm.uninstalled", service=self.SERVICE_NAME)

    def start(self) -> None:
        """Start the Astridr service."""
        logger.info("nssm.starting", service=self.SERVICE_NAME)
        self._run_nssm(["start", self.SERVICE_NAME])
        logger.info("nssm.started", service=self.SERVICE_NAME)

    def stop(self) -> None:
        """Stop the Astridr service."""
        logger.info("nssm.stopping", service=self.SERVICE_NAME)
        self._run_nssm(["stop", self.SERVICE_NAME])
        logger.info("nssm.stopped", service=self.SERVICE_NAME)

    def restart(self) -> None:
        """Restart the Astridr service."""
        logger.info("nssm.restarting", service=self.SERVICE_NAME)
        self._run_nssm(["restart", self.SERVICE_NAME])
        logger.info("nssm.restarted", service=self.SERVICE_NAME)

    def status(self) -> str:
        """Query the current service status.

        Returns:
            Status string: SERVICE_RUNNING, SERVICE_STOPPED,
            SERVICE_PAUSED, or SERVICE_NOT_FOUND.
        """
        try:
            result = self._run_nssm(["status", self.SERVICE_NAME], check=False)
            status_text = result.stdout.strip()
            logger.info(
                "nssm.status",
                service=self.SERVICE_NAME,
                status=status_text,
            )
            return status_text
        except NSSMError as exc:
            logger.warning("nssm.status_error", error=str(exc))
            return "SERVICE_NOT_FOUND"

    def _set(self, param: str, *values: str) -> None:
        """Set an NSSM service parameter."""
        self._run_nssm(["set", self.SERVICE_NAME, param, *values])

    def _run_nssm(
        self, args: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Execute an NSSM command.

        Args:
            args: Command arguments to pass to nssm.exe.
            check: If True, raise NSSMError on non-zero exit.

        Returns:
            The completed process result.

        Raises:
            NSSMError: If the command fails and check is True.
        """
        cmd = [self.nssm, *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise NSSMError(
                f"NSSM not found at '{self.nssm}'. "
                "Install from https://nssm.cc/ and add to PATH."
            )
        except subprocess.TimeoutExpired:
            raise NSSMError(f"NSSM command timed out: {' '.join(cmd)}")

        if check and result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise NSSMError(
                f"NSSM command failed (rc={result.returncode}): {stderr}"
            )

        return result


def main() -> None:
    """CLI entry point for NSSM service management."""
    parser = argparse.ArgumentParser(
        description="Manage the Astridr Windows service via NSSM",
        prog="nssm_setup",
    )
    parser.add_argument(
        "command",
        choices=["install", "uninstall", "start", "stop", "restart", "status"],
        help="Service management command",
    )
    parser.add_argument(
        "--nssm-path",
        default="nssm.exe",
        help="Path to nssm.exe (default: nssm.exe in PATH)",
    )
    args = parser.parse_args()

    service = NSSMService(nssm_path=args.nssm_path)

    try:
        match args.command:
            case "install":
                service.install()
            case "uninstall":
                service.uninstall()
            case "start":
                service.start()
            case "stop":
                service.stop()
            case "restart":
                service.restart()
            case "status":
                status = service.status()
                print(f"Service status: {status}")
    except NSSMError as exc:
        logger.error("nssm.error", command=args.command, error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
