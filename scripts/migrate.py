"""Migration script: Antidote v0.1.0 (Mac) -> Astridr (Windows).

Handles importing an exported migration zip from the Mac version and
converting all data formats to the new Astridr schema.

Usage:
    python scripts/migrate.py import path/to/migration.zip
    python scripts/migrate.py import --dry-run path/to/migration.zip
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from astridr.engine.config import ProfileConfig

logger = structlog.get_logger()

# Default Astridr directories
DEFAULT_ASTRIDR_ROOT = Path.home() / ".astridr"


@dataclass
class MigrationReport:
    """Tracks migration results, counts, and warnings."""

    profiles_migrated: int = 0
    memory_records_migrated: int = 0
    identity_files_copied: int = 0
    secrets_found: int = 0
    secrets_placeholder: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Whether the migration completed without errors."""
        return len(self.errors) == 0

    def summary(self) -> str:
        """Generate a human-readable summary."""
        lines = [
            "=== Astridr Migration Report ===",
            f"Profiles migrated:       {self.profiles_migrated}",
            f"Memory records migrated:  {self.memory_records_migrated}",
            f"Identity files copied:    {self.identity_files_copied}",
            f"Secrets found:           {self.secrets_found}",
            f"Secrets as placeholder:  {self.secrets_placeholder}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        if self.errors:
            lines.append("")
            lines.append("Errors:")
            for e in self.errors:
                lines.append(f"  - {e}")
        lines.append("")
        status = "SUCCESS" if self.success else "FAILED"
        lines.append(f"Overall: {status}")
        return "\n".join(lines)


def convert_config_to_profiles(config_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Antidote v0.1.0 config.json format to Astridr profiles.yaml format.

    The old format stored a flat config with a single profile's settings.
    The new format uses a list of ProfileConfig-compatible dicts.

    Args:
        config_data: Parsed JSON from the old config.json.

    Returns:
        List of profile dicts ready for YAML serialization.
    """
    profiles: list[dict[str, Any]] = []

    # Old format might have a single profile or a list
    old_profiles = config_data.get("profiles", [])
    if not old_profiles:
        # Treat the entire config as a single default profile
        profile = _convert_single_profile(config_data, profile_id="default")
        if profile:
            profiles.append(profile)
    else:
        for i, old_profile in enumerate(old_profiles):
            pid = old_profile.get("id", old_profile.get("name", f"profile-{i}"))
            profile = _convert_single_profile(old_profile, profile_id=pid)
            if profile:
                profiles.append(profile)

    return profiles


def _convert_single_profile(
    data: dict[str, Any], profile_id: str
) -> dict[str, Any] | None:
    """Convert a single profile from old format to new format."""
    name = data.get("name", profile_id.replace("-", " ").title())
    channels = data.get("channels", [])
    model = data.get("model", data.get("default_model", "anthropic/claude-sonnet-4-5"))
    fallback = data.get("fallback_model", "ollama/llama3.2:8b")
    max_rounds = data.get("max_rounds", 10)

    # Budget conversion
    budget_data = data.get("budget", {})
    budget = {
        "daily_usd": budget_data.get("daily", budget_data.get("daily_usd", 10.0)),
        "monthly_usd": budget_data.get("monthly", budget_data.get("monthly_usd", 200.0)),
    }

    # Validate via Pydantic
    try:
        validated = ProfileConfig(
            id=profile_id,
            name=name,
            channels=channels,
            budget=budget,
            model_default=model,
            model_fallback=fallback,
            max_rounds=max_rounds,
        )
        return validated.model_dump()
    except Exception as exc:
        logger.warning(
            "migrate.profile_validation_failed",
            profile_id=profile_id,
            error=str(exc),
        )
        return None


def migrate_memory_db(
    db_path: Path, *, dry_run: bool = False
) -> int:
    """Migrate the SQLite memory database schema.

    Adds ``profile_id`` and ``group_id`` columns if they don't exist.

    Args:
        db_path: Path to the SQLite database.
        dry_run: If True, only report what would change.

    Returns:
        Number of records in the memories table.
    """
    if not db_path.exists():
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()

        # Check existing columns
        cursor.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}

        if "memories" not in _get_tables(cursor):
            logger.info("migrate.no_memories_table")
            return 0

        migrations_needed: list[str] = []
        if "profile_id" not in columns:
            migrations_needed.append(
                "ALTER TABLE memories ADD COLUMN profile_id TEXT DEFAULT 'default'"
            )
        if "group_id" not in columns:
            migrations_needed.append(
                "ALTER TABLE memories ADD COLUMN group_id TEXT DEFAULT NULL"
            )

        if dry_run:
            for sql in migrations_needed:
                logger.info("migrate.dry_run_sql", sql=sql)
        else:
            for sql in migrations_needed:
                cursor.execute(sql)
            conn.commit()

        # Count records
        cursor.execute("SELECT COUNT(*) FROM memories")
        count: int = cursor.fetchone()[0]
        return count
    finally:
        conn.close()


def _get_tables(cursor: sqlite3.Cursor) -> set[str]:
    """Return all table names in the database."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def extract_secrets(config_data: dict[str, Any]) -> list[dict[str, str]]:
    """Extract secret references from the old config.

    Returns a list of dicts with ``key``, ``old_value`` (masked), and
    ``migration_note`` fields.
    """
    secrets: list[dict[str, str]] = []
    secret_keys = [
        "api_key", "token", "password", "secret",
        "bot_token", "app_token",
    ]

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                current_path = f"{path}.{k}" if path else k
                if any(sk in k.lower() for sk in secret_keys) and isinstance(v, str) and v:
                    masked = v[:4] + "..." + v[-4:] if len(v) > 8 else "***"
                    secrets.append({
                        "key": current_path,
                        "old_value_masked": masked,
                        "migration_note": (
                            "Re-encrypt using DPAPI or 1Password CLI. "
                            "Old Fernet-encrypted values cannot be used directly."
                        ),
                    })
                else:
                    _walk(v, current_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(config_data)
    return secrets


class AntidoteMigrator:
    """Orchestrates migration from Antidote v0.1.0 to Astridr.

    Steps:
    1. Extract zip to temporary directory
    2. Convert config.json to profiles.yaml
    3. Migrate SQLite memory DB schema
    4. Copy soul.md to identity/
    5. Extract and report secrets
    6. Generate migration report
    """

    def __init__(
        self,
        zip_path: Path,
        target_root: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.zip_path = zip_path
        self.target_root = target_root or DEFAULT_ASTRIDR_ROOT
        self.dry_run = dry_run
        self.report = MigrationReport()

    def run(self) -> MigrationReport:
        """Execute the full migration."""
        logger.info(
            "migrate.starting",
            source=str(self.zip_path),
            target=str(self.target_root),
            dry_run=self.dry_run,
        )

        if not self.zip_path.exists():
            self.report.errors.append(f"Zip file not found: {self.zip_path}")
            return self.report

        if not zipfile.is_zipfile(str(self.zip_path)):
            self.report.errors.append(f"Not a valid zip file: {self.zip_path}")
            return self.report

        with tempfile.TemporaryDirectory(prefix="astridr-migrate-") as tmpdir:
            tmp = Path(tmpdir)
            self._extract_zip(tmp)
            self._migrate_config(tmp)
            self._migrate_memory(tmp)
            self._migrate_identity(tmp)
            self._migrate_secrets(tmp)

        logger.info(
            "migrate.complete",
            success=self.report.success,
            profiles=self.report.profiles_migrated,
            records=self.report.memory_records_migrated,
        )
        return self.report

    def _extract_zip(self, target: Path) -> None:
        """Extract the migration zip to a temp directory."""
        try:
            with zipfile.ZipFile(str(self.zip_path), "r") as zf:
                zf.extractall(str(target))
            logger.info("migrate.extracted", path=str(target))
        except zipfile.BadZipFile as exc:
            self.report.errors.append(f"Failed to extract zip: {exc}")

    def _migrate_config(self, source: Path) -> None:
        """Convert config.json to profiles.yaml."""
        config_file = self._find_file(source, "config.json")
        if not config_file:
            self.report.warnings.append("No config.json found in migration zip")
            return

        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self.report.errors.append(f"Failed to read config.json: {exc}")
            return

        profiles = convert_config_to_profiles(config_data)
        self.report.profiles_migrated = len(profiles)

        if not profiles:
            self.report.warnings.append("No profiles could be converted")
            return

        profiles_yaml = {"profiles": profiles}
        config_dir = self.target_root / "config"

        if self.dry_run:
            logger.info(
                "migrate.dry_run.config",
                profiles_count=len(profiles),
                target=str(config_dir / "profiles.yaml"),
            )
        else:
            config_dir.mkdir(parents=True, exist_ok=True)
            output = config_dir / "profiles.yaml"
            output.write_text(
                yaml.dump(profiles_yaml, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            logger.info("migrate.config_written", path=str(output))

    def _migrate_memory(self, source: Path) -> None:
        """Migrate the SQLite memory database."""
        db_file = self._find_file(source, "memory.db")
        if not db_file:
            self.report.warnings.append("No memory.db found in migration zip")
            return

        memory_dir = self.target_root / "memory"

        if self.dry_run:
            count = migrate_memory_db(db_file, dry_run=True)
            self.report.memory_records_migrated = count
            logger.info("migrate.dry_run.memory", records=count)
        else:
            memory_dir.mkdir(parents=True, exist_ok=True)
            target_db = memory_dir / "memory.db"
            shutil.copy2(str(db_file), str(target_db))
            count = migrate_memory_db(target_db, dry_run=False)
            self.report.memory_records_migrated = count
            logger.info("migrate.memory_migrated", records=count)

    def _migrate_identity(self, source: Path) -> None:
        """Copy soul.md to identity/ directory."""
        soul_file = self._find_file(source, "soul.md")
        if not soul_file:
            self.report.warnings.append("No soul.md found in migration zip")
            return

        identity_dir = self.target_root / "identity"

        if self.dry_run:
            self.report.identity_files_copied = 1
            logger.info("migrate.dry_run.identity", file="soul.md")
        else:
            identity_dir.mkdir(parents=True, exist_ok=True)
            target = identity_dir / "soul.md"
            shutil.copy2(str(soul_file), str(target))
            self.report.identity_files_copied = 1
            logger.info("migrate.identity_copied", path=str(target))

    def _migrate_secrets(self, source: Path) -> None:
        """Extract and report secrets from old config."""
        config_file = self._find_file(source, "config.json")
        if not config_file:
            return

        try:
            config_data = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        secrets = extract_secrets(config_data)
        self.report.secrets_found = len(secrets)
        self.report.secrets_placeholder = len(secrets)

        if secrets:
            self.report.warnings.append(
                f"Found {len(secrets)} secret(s) that need re-encryption. "
                "Old Fernet-encrypted values must be re-encrypted with "
                "DPAPI (Windows) or 1Password CLI."
            )
            for secret in secrets:
                logger.info(
                    "migrate.secret_found",
                    key=secret["key"],
                    note=secret["migration_note"],
                )

    @staticmethod
    def _find_file(root: Path, filename: str) -> Path | None:
        """Find a file by name in a directory tree."""
        for path in root.rglob(filename):
            return path
        return None


def main() -> None:
    """CLI entry point for migration."""
    parser = argparse.ArgumentParser(
        description="Migrate from Antidote v0.1.0 to Astridr",
        prog="migrate",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import", help="Import from migration zip"
    )
    import_parser.add_argument(
        "zip_path", type=Path, help="Path to the migration zip file"
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes",
    )
    import_parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help=f"Target Astridr root (default: {DEFAULT_ASTRIDR_ROOT})",
    )

    args = parser.parse_args()

    if args.command == "import":
        migrator = AntidoteMigrator(
            zip_path=args.zip_path,
            target_root=args.target,
            dry_run=args.dry_run,
        )
        report = migrator.run()
        print(report.summary())
        sys.exit(0 if report.success else 1)


if __name__ == "__main__":
    main()
