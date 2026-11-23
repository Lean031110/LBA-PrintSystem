from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from collections.abc import Iterator
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "deploy" / "scripts"

spec = importlib.util.spec_from_file_location(
    "validate_config_archive", SCRIPTS / "validate_config_archive.py"
)
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class ProxmoxProvisioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="lba-proxmox-test-")
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.template = self.base / "template.tar.zst"
        self.log = self.base / "commands.log"
        self.write_mock(
            "pveam",
            """#!/bin/bash
echo "pveam $*" >> "$MOCK_PVE_LOG"
if [[ "$1" == download && "${MOCK_DOWNLOAD_FAIL:-0}" == 1 ]]; then exit 44; fi
if [[ "$1" == download ]]; then touch "$MOCK_TEMPLATE_FILE"; fi
""",
        )
        self.write_mock(
            "pvesm",
            """#!/bin/bash
if [[ "$1" == path && -f "$MOCK_TEMPLATE_FILE" ]]; then echo "$MOCK_TEMPLATE_FILE"; else exit 1; fi
""",
        )
        self.write_mock(
            "pct",
            """#!/bin/bash
if [[ "$1" == config ]]; then [[ "${MOCK_CT_EXISTS:-0}" == 1 ]]; exit $?; fi
echo "pct $*" >> "$MOCK_PVE_LOG"
""",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_mock(self, name: str, content: str) -> None:
        path = self.bin / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def run_script(self, **extra: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "MOCK_PVE_LOG": str(self.log),
            "MOCK_TEMPLATE_FILE": str(self.template),
            "CTID": "321",
            "HOSTNAME": "lba-test",
            **extra,
        }
        return subprocess.run(
            ["bash", str(ROOT / "deploy/proxmox/create_lba_ct.sh")],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )

    def test_uses_existing_template_without_updating_or_downloading(self) -> None:
        self.template.touch()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("Usando plantilla local existente", result.stdout)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn("pct create 321", calls)
        self.assertNotIn("pveam", calls)

    def test_download_failure_is_reported_and_ct_is_not_created(self) -> None:
        result = self.run_script(MOCK_DOWNLOAD_FAIL="1")
        self.assertEqual(result.returncode, 44)
        calls = self.log.read_text(encoding="utf-8")
        self.assertIn("pveam download", calls)
        self.assertNotIn("pct create", calls)

    def test_existing_ctid_is_rejected_before_template_operations(self) -> None:
        result = self.run_script(MOCK_CT_EXISTS="1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CTID 321 ya existe", result.stderr)
        self.assertFalse(self.log.exists())


class DemoSafetyTests(unittest.TestCase):
    def test_walkthrough_uses_private_ephemeral_paths_and_cleans_by_default(self) -> None:
        source = (SCRIPTS / "demo_walkthrough.sh").read_text(encoding="utf-8")
        self.assertIn("umask 077", source)
        self.assertIn('RUN_DIR="$(mktemp -d /tmp/lba-demo-', source)
        self.assertIn('COOKIE_FILE="$RUN_DIR/session.cookies"', source)
        self.assertIn('SIM_LOG="$RUN_DIR/simulator.log"', source)
        self.assertIn('rm -rf -- "$RUN_DIR"', source)
        self.assertIn('LBA_DEMO_KEEP:-0', source)
        self.assertNotIn("/tmp/lba-demo-cookies", source)

    def test_walkthrough_rejects_remote_base_before_starting_services(self) -> None:
        result = subprocess.run(
            ["bash", str(ROOT / "deploy/scripts/demo_walkthrough.sh")],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "BASE": "https://example.com"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Destino remoto rechazado", result.stderr)
        self.assertNotIn("esperando a la API", result.stdout)

    def test_walkthrough_rejects_url_credentials(self) -> None:
        result = subprocess.run(
            ["bash", str(ROOT / "deploy/scripts/demo_walkthrough.sh")],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "BASE": "http://user:password@127.0.0.1:8000"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("sin credenciales", result.stderr)


class ConfigArchiveValidationTests(unittest.TestCase):
    def make_archive(self, members: list[tuple[str, str, int]]) -> str:
        handle, archive = tempfile.mkstemp(suffix=".tar.gz")
        os.close(handle)
        with tarfile.open(archive, "w:gz") as tf:
            for name, kind, size in members:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/etc/passwd"
                elif kind == "hardlink":
                    info.type = tarfile.LNKTYPE
                    info.linkname = "etc/lba-print/secret"
                elif kind == "file":
                    info.size = size
                    tf.addfile(info, io.BytesIO(b"x" * size))
                    continue
                else:
                    info.size = size
                tf.addfile(info)
        self.addCleanup(lambda: Path(archive).unlink(missing_ok=True))
        return archive

    def test_accepts_backup_layout_with_dot_prefix(self) -> None:
        archive = self.make_archive(
            [
                ("./etc/lba-print", "dir", 0),
                ("./etc/lba-print/lba-print.env", "file", 12),
            ]
        )
        validator.validate_config_archive(archive)

    def test_rejects_parent_traversal_that_lstrip_would_hide(self) -> None:
        archive = self.make_archive(
            [("../../etc/lba-print/escape", "file", 1)]
        )
        with self.assertRaisesRegex(ValueError, "inseguro"):
            validator.validate_config_archive(archive)

    def test_rejects_absolute_and_outside_paths(self) -> None:
        for name in ("/etc/lba-print/secret", "etc/passwd"):
            with self.subTest(name=name):
                archive = self.make_archive([(name, "file", 1)])
                with self.assertRaises(ValueError):
                    validator.validate_config_archive(archive)

    def test_rejects_links_duplicates_and_file_parent_conflicts(self) -> None:
        cases = [
            [("etc/lba-print/link", "symlink", 0)],
            [
                ("etc/lba-print/a", "file", 1),
                ("etc/lba-print/a", "file", 1),
            ],
            [
                ("etc/lba-print", "file", 0),
                ("etc/lba-print/child", "file", 1),
            ],
        ]
        for members in cases:
            with self.subTest(members=members):
                archive = self.make_archive(members)
                with self.assertRaises(ValueError):
                    validator.validate_config_archive(archive)

    def test_rejects_oversized_configuration(self) -> None:
        archive = self.make_archive([("etc/lba-print/large", "file", 2)])
        with mock.patch.object(validator, "MAX_TOTAL_FILE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "supera el límite"):
                validator.validate_config_archive(archive)


class RetryHelperTests(unittest.TestCase):
    def run_bash(self, body: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        script = f'source "{SCRIPTS / "lib_common.sh"}"\n{body}'
        child_env = os.environ.copy()
        child_env.update(env or {})
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, env=child_env, timeout=10
        )

    def test_retries_until_success_with_zero_wait(self) -> None:
        result = self.run_bash(
            "count=0; flaky(){ count=$((count+1)); (( count < 3 )) && return 9; return 0; }; "
            "sleep(){ :; }; lba_retry unit flaky; test \"$count\" = 3",
            {
                "LBA_DOWNLOAD_RETRIES": "3",
                "LBA_RETRY_BASE_SECONDS": "0",
                "LBA_RETRY_MAX_SECONDS": "1",
                "LBA_RETRY_JITTER_SECONDS": "0",
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("intento 3/3", result.stdout)

    def test_returns_failure_after_configured_attempts(self) -> None:
        result = self.run_bash(
            "always_fail(){ return 7; }; sleep(){ :; }; lba_retry unit always_fail",
            {
                "LBA_DOWNLOAD_RETRIES": "2",
                "LBA_RETRY_BASE_SECONDS": "0",
                "LBA_RETRY_MAX_SECONDS": "1",
                "LBA_RETRY_JITTER_SECONDS": "0",
            },
        )
        self.assertEqual(result.returncode, 7)
        self.assertIn("agotados los reintentos", result.stderr)

    def test_rejects_invalid_retry_configuration(self) -> None:
        result = self.run_bash(
            "lba_retry unit true", {"LBA_DOWNLOAD_RETRIES": "0"}
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entero positivo", result.stderr)


class DeployIntegrationTests(unittest.TestCase):
    """Root-script integration checks, isolated to TemporaryDirectory paths."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sudo = shutil.which("sudo")
        if not cls.sudo:
            raise unittest.SkipTest("sudo no está disponible para pruebas root aisladas")
        cls.mock_root = tempfile.TemporaryDirectory(prefix="lba-script-mocks-")
        cls.mock_bin = Path(cls.mock_root.name)
        cls.write_mock(
            "sqlite3",
            """#!/usr/bin/python3
import ast, os, sqlite3, sys
db, query = sys.argv[1], sys.argv[2]
if query.startswith('.backup '):
    target = ast.literal_eval(query[len('.backup '):].strip())
    with sqlite3.connect(db) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
elif 'PRAGMA integrity_check' in query:
    if os.environ.get('MOCK_SQLITE_BAD') == '1':
        print('corrupt')
    else:
        print(sqlite3.connect(db).execute('PRAGMA integrity_check').fetchone()[0])
else:
    raise SystemExit('query SQLite mock no soportada')
""",
        )
        cls.write_mock(
            "systemctl",
            """#!/usr/bin/python3
import json, os, sys
with open(os.environ['MOCK_SYSTEMCTL_LOG'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
""",
        )
        cls.write_mock(
            "curl",
            """#!/usr/bin/python3
import os, sys
with open(os.environ['MOCK_CURL_LOG'], 'a', encoding='utf-8') as f:
    f.write(' '.join(sys.argv[1:]) + '\\n')
if os.environ.get('MOCK_CURL_FAIL') == '1':
    raise SystemExit(22)
print('{"status":"ok"}')
""",
        )
        cls.write_mock("sleep", "#!/bin/sh\nexit 0\n")
        cls.write_mock("rsync", "#!/bin/sh\necho called >> \"$MOCK_RSYNC_LOG\"\nexit 0\n")
        cls.write_mock(
            "mv",
            """#!/bin/bash
if [[ \"${MOCK_FAIL_CONFIG_MOVE:-0}\" == 1 && \"${2:-}\" == \"${LBA_RESTORE_ENV_DIR:-}\" ]]; then
    exit 73
fi
exec /usr/bin/mv \"$@\"
""",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if getattr(cls, "mock_root", None):
            cls.mock_root.cleanup()

    @classmethod
    def write_mock(cls, name: str, content: str) -> None:
        path = cls.mock_bin / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def root_command(self, env: dict[str, str], *command: str) -> subprocess.CompletedProcess[str]:
        child_env = {
            "PATH": f"{self.mock_bin}:{os.environ['PATH']}",
            "HOME": os.environ.get("HOME", "/root"),
        }
        child_env.update(env)
        args = [self.sudo, "-n", "env", *(f"{key}={value}" for key, value in child_env.items()), *command]
        return subprocess.run(args, capture_output=True, text=True, timeout=30)

    @contextmanager
    def isolated_tempdir(self, prefix: str) -> Iterator[Path]:
        directory = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            yield directory
        finally:
            subprocess.run(
                [self.sudo, "-n", "chown", "-R", "ubuntu:ubuntu", str(directory)],
                check=True, capture_output=True, text=True, timeout=10,
            )
            shutil.rmtree(directory)

    @staticmethod
    def create_db(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS fixture (value TEXT)")
            db.execute("DELETE FROM fixture")
            db.execute("INSERT INTO fixture VALUES (?)", (value,))

    @staticmethod
    def db_value(path: Path) -> str:
        with sqlite3.connect(path) as db:
            return db.execute("SELECT value FROM fixture").fetchone()[0]

    def make_config_archive(self, path: Path, port: int, marker: str) -> None:
        data = f"LBA_PORT={port}\nMARKER={marker}\n".encode()
        with tarfile.open(path, "w:gz") as tf:
            info = tarfile.TarInfo("etc/lba-print")
            info.type = tarfile.DIRTYPE
            tf.addfile(info)
            info = tarfile.TarInfo("etc/lba-print/lba-print.env")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

    def common_env(self, base: Path) -> dict[str, str]:
        var_dir = base / "var"
        env_dir = base / "etc" / "lba-print"
        backups = base / "backups"
        var_dir.mkdir(parents=True, exist_ok=True)
        env_dir.mkdir(parents=True, exist_ok=True)
        backups.mkdir(parents=True, exist_ok=True)
        return {
            "LBA_BACKUP_VAR_DIR": str(var_dir),
            "LBA_BACKUP_ENV_DIR": str(env_dir),
            "LBA_BACKUP_DIR": str(backups),
            "LBA_RESTORE_VAR_DIR": str(var_dir),
            "LBA_RESTORE_ENV_DIR": str(env_dir),
            "LBA_RESTORE_STAGE_ROOT": str(base / "stage"),
            "LBA_SERVICE_USER": "ubuntu",
            "LBA_SERVICE_GROUP": "ubuntu",
            "MOCK_SYSTEMCTL_LOG": str(base / "systemctl.log"),
            "MOCK_CURL_LOG": str(base / "curl.log"),
        }

    def test_backup_creates_private_verified_set(self) -> None:
        with self.isolated_tempdir("lba-backup-test-") as base:
            env = self.common_env(base)
            self.create_db(base / "var/lba.db", "old")
            (base / "etc/lba-print/lba-print.env").write_text(
                "LBA_PORT=8000\nAPI_SECRET=isolated-test-secret\n", encoding="utf-8"
            )
            result = self.root_command(env, "bash", str(SCRIPTS / "backup.sh"))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            listing = self.root_command(
                env, "bash", "-c",
                'find "$LBA_BACKUP_DIR" -maxdepth 1 -type f -printf "%f %m\\n"; '
                'cd "$LBA_BACKUP_DIR" && sha256sum -c *.sha256',
            )
            self.assertEqual(listing.returncode, 0, listing.stderr + listing.stdout)
            self.assertIn("600", listing.stdout)
            self.assertIn("OK", listing.stdout)
            self.assertIn("lba-config-", listing.stdout)

    def test_backup_rejects_symlink_and_hardlink_config(self) -> None:
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(link_kind=link_kind), self.isolated_tempdir(
                f"lba-backup-{link_kind}-"
            ) as base:
                env = self.common_env(base)
                self.create_db(base / "var/lba.db", "old")
                source = base / "etc/lba-print/secret.env"
                source.write_text("SECRET=value\n", encoding="utf-8")
                linked = base / "etc/lba-print/linked.env"
                if link_kind == "symlink":
                    linked.symlink_to(source)
                else:
                    os.link(source, linked)
                result = self.root_command(env, "bash", str(SCRIPTS / "backup.sh"))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("symlinks o hardlinks", result.stderr)
                self.assertEqual(list((base / "backups").glob("lba-*")), [])

    def test_restore_success_uses_backup_port_and_replaces_state(self) -> None:
        with self.isolated_tempdir("lba-restore-test-") as base:
            env = self.common_env(base)
            self.create_db(base / "var/lba.db", "old")
            (base / "etc/lba-print/lba-print.env").write_text("LBA_PORT=8000\n", encoding="utf-8")
            self.create_db(base / "new.db", "new")
            archive = base / "new-config.tar.gz"
            self.make_config_archive(archive, 8765, "restored")
            result = self.root_command(
                env, "bash", str(SCRIPTS / "restore.sh"), str(base / "new.db"), str(archive)
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(self.db_value(base / "var/lba.db"), "new")
            restored = (base / "etc/lba-print/lba-print.env").read_text(encoding="utf-8")
            self.assertIn("LBA_PORT=8765", restored)
            self.assertIn("restored", restored)
            self.assertIn("127.0.0.1:8765/api/v1/health", (base / "curl.log").read_text())

    def test_restore_preserves_stage_root_mode_and_normalizes_all_config_permissions(self) -> None:
        with self.isolated_tempdir("lba-restore-permissions-") as base:
            env = self.common_env(base)
            env.pop("LBA_RESTORE_STAGE_ROOT")  # ejercicio de ruta predeterminada
            stage_root = base / "etc"
            stage_root.chmod(0o751)
            self.create_db(base / "var/lba.db", "old")
            self.create_db(base / "new.db", "new")
            archive = base / "permissive-config.tar.gz"
            with tarfile.open(archive, "w:gz") as tf:
                for name, kind, mode, data in (
                    ("etc/lba-print", tarfile.DIRTYPE, 0o777, None),
                    ("etc/lba-print/lba-print.env", tarfile.REGTYPE, 0o777,
                     b"LBA_PORT=8765\n"),
                    ("etc/lba-print/nested", tarfile.DIRTYPE, 0o777, None),
                    ("etc/lba-print/nested/token", tarfile.REGTYPE, 0o666,
                     b"sensitive\n"),
                ):
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.mode = mode
                    if data is not None:
                        info.size = len(data)
                        tf.addfile(info, io.BytesIO(data))
                    else:
                        tf.addfile(info)
            result = self.root_command(
                env, "bash", str(SCRIPTS / "restore.sh"), str(base / "new.db"),
                str(archive),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(stage_root.stat().st_mode & 0o777, 0o751)
            restored_root = base / "etc/lba-print"
            self.assertEqual(restored_root.stat().st_mode & 0o777, 0o750)
            self.assertEqual((restored_root / "nested").stat().st_mode & 0o777, 0o750)
            self.assertEqual((restored_root / "lba-print.env").stat().st_mode & 0o777, 0o640)
            self.assertEqual((restored_root / "nested/token").stat().st_mode & 0o777, 0o640)

    def test_restore_health_failure_rolls_back_database_and_config(self) -> None:
        with self.isolated_tempdir("lba-restore-rollback-") as base:
            env = self.common_env(base)
            env["MOCK_CURL_FAIL"] = "1"
            self.create_db(base / "var/lba.db", "old")
            (base / "etc/lba-print/lba-print.env").write_text("LBA_PORT=8000\nMARKER=old\n", encoding="utf-8")
            self.create_db(base / "new.db", "new")
            archive = base / "new-config.tar.gz"
            self.make_config_archive(archive, 8765, "new")
            result = self.root_command(
                env, "bash", str(SCRIPTS / "restore.sh"), str(base / "new.db"), str(archive)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.db_value(base / "var/lba.db"), "old")
            restored = (base / "etc/lba-print/lba-print.env").read_text(encoding="utf-8")
            self.assertIn("MARKER=old", restored)
            stage_check = self.root_command(
                env, "bash", "-c",
                'find "$LBA_RESTORE_STAGE_ROOT" -mindepth 1 -maxdepth 1 -print',
            )
            self.assertEqual(stage_check.returncode, 0, stage_check.stderr)
            self.assertEqual(stage_check.stdout.strip(), "")

    def test_restore_config_move_failure_preserves_original_directory(self) -> None:
        with self.isolated_tempdir("lba-restore-mv-failure-") as base:
            env = self.common_env(base)
            env["MOCK_FAIL_CONFIG_MOVE"] = "1"
            self.create_db(base / "var/lba.db", "old")
            (base / "etc/lba-print/lba-print.env").write_text(
                "LBA_PORT=8000\nMARKER=original\n", encoding="utf-8"
            )
            self.create_db(base / "new.db", "new")
            archive = base / "new-config.tar.gz"
            self.make_config_archive(archive, 8765, "new")
            result = self.root_command(
                env, "bash", str(SCRIPTS / "restore.sh"), str(base / "new.db"), str(archive)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.db_value(base / "var/lba.db"), "old")
            restored = (base / "etc/lba-print/lba-print.env").read_text(encoding="utf-8")
            self.assertIn("MARKER=original", restored)

    def test_failed_backup_aborts_update_before_sync(self) -> None:
        with self.isolated_tempdir("lba-update-failure-") as base:
            env = self.common_env(base)
            env.update(
                {
                    "LBA_INSTALL_DIR": str(base / "install"),
                    "LBA_UPDATE_VAR_DIR": str(base / "var"),
                    "LBA_UPDATE_ENV_FILE": str(base / "etc/lba-print/lba-print.env"),
                    "LBA_SYSTEMD_DIR": str(base / "systemd"),
                    "LBA_SERVICE_USER": "root",
                    "LBA_SERVICE_GROUP": "root",
                    "MOCK_RSYNC_LOG": str(base / "rsync.log"),
                    "MOCK_SQLITE_BAD": "1",
                }
            )
            install = base / "install"
            (install / "server").mkdir(parents=True)
            (install / "server/installed-marker").write_text("unchanged", encoding="utf-8")
            (base / "etc/lba-print/lba-print.env").write_text("LBA_PORT=8000\n", encoding="utf-8")
            self.create_db(base / "var/lba.db", "old")
            result = self.root_command(
                env, "bash", str(SCRIPTS / "update.sh"), str(ROOT)
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((install / "server/installed-marker").read_text(), "unchanged")
            self.assertFalse((base / "rsync.log").exists())
            self.assertIn("integrity_check", result.stdout + result.stderr)

    def test_uninstall_preserves_by_default_and_purges_only_explicitly(self) -> None:
        with self.isolated_tempdir("lba-uninstall-test-") as base:
            install = base / "install"
            var = base / "var"
            env_dir = base / "etc/lba-print"
            systemd = base / "systemd"
            for path in (install, var, env_dir, systemd):
                path.mkdir(parents=True, exist_ok=True)
            (install / "code").write_text("x")
            (var / "lba.db").write_text("data")
            (env_dir / "lba-print.env").write_text("secret")
            for service in ("api", "worker", "simulator"):
                (systemd / f"lba-print-{service}.service").write_text("unit")
            env = {
                "PATH": f"{self.mock_bin}:{os.environ['PATH']}",
                "HOME": os.environ.get("HOME", "/root"),
                "LBA_INSTALL_DIR": str(install),
                "LBA_UNINSTALL_VAR_DIR": str(var),
                "LBA_UNINSTALL_ENV_DIR": str(env_dir),
                "LBA_SYSTEMD_DIR": str(systemd),
                "MOCK_SYSTEMCTL_LOG": str(base / "systemctl.log"),
            }
            first = self.root_command(env, "bash", str(SCRIPTS / "uninstall.sh"))
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            self.assertFalse(install.exists())
            self.assertTrue((var / "lba.db").exists())
            self.assertTrue((env_dir / "lba-print.env").exists())
            self.assertFalse(any(systemd.glob("lba-print-*.service")))

            install.mkdir()
            (install / "code").write_text("x")
            second = self.root_command(env, "bash", str(SCRIPTS / "uninstall.sh"), "--purge-data")
            self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
            self.assertFalse(var.exists())
            self.assertFalse(env_dir.exists())


if __name__ == "__main__":
    unittest.main()
