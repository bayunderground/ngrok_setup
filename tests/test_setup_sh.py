import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SETUP = REPO / "setup.sh"


class SetupScriptTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = Path(self.dir.name)
        self.root = self.base / "root"
        self.home = self.base / "home"
        self.home.mkdir()
        self.os_release = self.base / "os-release"
        self.os_release.write_text("ID=debian\nVERSION_ID=\"13\"\n", encoding="utf-8")
        self.sshd_config = self.root / "etc/ssh/sshd_config"
        self.sshd_config.parent.mkdir(parents=True)
        self.original_sshd = (
            "Include /etc/ssh/sshd_config.d/*.conf\n"
            "KbdInteractiveAuthentication no\n"
            "UsePAM yes\n"
            "Subsystem\tsftp\t/usr/lib/openssh/sftp-server\n"
        )
        self.sshd_config.write_text(self.original_sshd, encoding="utf-8")
        self.env = dict(
            os.environ,
            NGROK_SSH_ROOT=str(self.root),
            NGROK_SSH_HOME=str(self.home),
            NGROK_SSH_OS_RELEASE=str(self.os_release),
            NGROK_SSH_ARCH="aarch64",
        )

    def tearDown(self):
        self.dir.cleanup()

    def run_setup(self, *args, env=None, real_root=False):
        run_env = dict(env or self.env)
        if real_root:
            run_env.pop("NGROK_SSH_ROOT")
        return subprocess.run(
            ["bash", str(SETUP), *args],
            env=run_env, capture_output=True, text=True, timeout=120,
        )

    def test_check_passes_on_debian13_arm64(self):
        result = self.run_setup("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("check passed", result.stdout)

    def test_check_fails_on_wrong_os(self):
        self.os_release.write_text("ID=ubuntu\nVERSION_ID=\"24.04\"\n", encoding="utf-8")
        result = self.run_setup("check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL  OS must be Debian 13", result.stdout)

    def test_check_fails_on_wrong_arch(self):
        env = dict(self.env, NGROK_SSH_ARCH="x86_64")
        result = self.run_setup("check", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL  architecture must be arm64", result.stdout)

    def test_dry_run_install_writes_nothing(self):
        result = self.run_setup("--dry-run", "install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("would install", result.stdout)
        self.assertFalse((self.root / "usr/local/lib/ngrok-ssh").exists())
        self.assertFalse((self.home / ".config").exists())

    def test_install_lays_out_files_with_expected_modes(self):
        result = self.run_setup("install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lib = self.root / "usr/local/lib/ngrok-ssh"
        self.assertTrue((lib / "scripts/ngrok_recover.py").exists())
        self.assertTrue((lib / "config/ngrok-ssh.yml").exists())
        self.assertTrue((self.root / "etc/systemd/system/ngrok-ssh.service").exists())
        dispatcher = self.root / "etc/NetworkManager/dispatcher.d/50-ngrok-ssh"
        self.assertTrue(os.access(dispatcher, os.X_OK))
        self.assertEqual(stat.S_IMODE(os.stat(lib / "scripts/ngrok_recover.py").st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(lib / "config/ngrok-ssh.yml").st_mode), 0o644)

    def test_install_creates_private_telegram_env_disabled_by_default(self):
        result = self.run_setup("install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        dest = self.home / ".config/ngrok-ssh/telegram.env"
        self.assertEqual(stat.S_IMODE(os.stat(dest).st_mode), 0o600)
        keys = [line.split("=", 1)[0] for line in dest.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(keys, ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ENABLED"])
        self.assertIn("TELEGRAM_ENABLED=0", dest.read_text(encoding="utf-8").splitlines())

    def test_reinstall_is_idempotent_and_keeps_credentials(self):
        self.run_setup("install")
        dest = self.home / ".config/ngrok-ssh/telegram.env"
        before = dest.read_text(encoding="utf-8")
        result = self.run_setup("install")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("kept existing", result.stdout)
        self.assertEqual(dest.read_text(encoding="utf-8"), before)

    @unittest.skipIf(os.geteuid() == 0, "must not run the real-system path as root")
    def test_install_refuses_without_root_on_real_system(self):
        result = self.run_setup("install", real_root=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must run as root", result.stderr)

    def test_uninstall_removes_project_files_and_keeps_credentials(self):
        self.run_setup("install")
        result = self.run_setup("uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.root / "usr/local/lib/ngrok-ssh").exists())
        self.assertFalse((self.root / "etc/systemd/system/ngrok-ssh.service").exists())
        self.assertFalse((self.root / "etc/NetworkManager/dispatcher.d/50-ngrok-ssh").exists())
        self.assertTrue((self.home / ".config/ngrok-ssh/telegram.env").exists())
        self.assertIn("kept credentials and state", result.stdout)

    def test_uninstall_keeps_modified_dispatcher_file(self):
        self.run_setup("install")
        dispatcher = self.root / "etc/NetworkManager/dispatcher.d/50-ngrok-ssh"
        dispatcher.write_text("#!/bin/sh\necho edited\n", encoding="utf-8")
        result = self.run_setup("uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(dispatcher.exists())
        self.assertIn("modified", result.stdout)

    def test_dry_run_uninstall_removes_nothing(self):
        self.run_setup("install")
        result = self.run_setup("--dry-run", "uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("would remove", result.stdout)
        self.assertTrue((self.root / "usr/local/lib/ngrok-ssh").exists())

    def test_uninstall_without_install_is_harmless(self):
        result = self.run_setup("uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_setup("uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipIf(os.geteuid() == 0, "must not run the real-system path as root")
    def test_uninstall_refuses_without_root_on_real_system(self):
        result = self.run_setup("uninstall", real_root=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must run as root", result.stderr)

    def test_install_adds_bliss_only_password_block_once(self):
        self.run_setup("install")
        self.run_setup("install")
        text = self.sshd_config.read_text(encoding="utf-8")
        self.assertEqual(text.count("# BEGIN ngrok-ssh"), 1)
        self.assertTrue(text.startswith(self.original_sshd))
        self.assertIn("Match User bliss\n    PasswordAuthentication yes\n", text)
        self.assertTrue((self.root / "etc/ssh/sshd_config.bak-ngrok-ssh").exists())

    def test_install_refuses_when_sshd_config_missing(self):
        self.sshd_config.unlink()
        result = self.run_setup("install")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stderr)

    def test_uninstall_restores_sshd_config_without_block(self):
        self.run_setup("install")
        result = self.run_setup("uninstall")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.sshd_config.read_text(encoding="utf-8"), self.original_sshd)

    def test_dry_run_install_leaves_sshd_config_unchanged(self):
        self.run_setup("--dry-run", "install")
        self.assertEqual(self.sshd_config.read_text(encoding="utf-8"), self.original_sshd)

    def test_status_reports_state_line_in_test_root(self):
        result = self.run_setup("status")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("state=", result.stdout)
        self.assertIn("units: skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
