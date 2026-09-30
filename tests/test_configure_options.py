"""验证预检保留实际参数并在未知选项时停止构建。"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigureOptionsTests(unittest.TestCase):
    def setUp(self):
        self.bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        if not self.bash or not Path(self.bash).exists():
            self.skipTest("未安装 Bash")
        self.temp = tempfile.TemporaryDirectory(prefix="lumora configure ")
        self.addCleanup(self.temp.cleanup)
        self.workdir = Path(self.temp.name)
        self.source = self.workdir / "ffmpeg"
        self.source.mkdir()
        self.log = self.workdir / "dist/logs.linux_amd64/configure-options.log"

    def run_check(self, contents, extra="", platform="linux_amd64"):
        configure = self.source / "configure"
        configure.write_text(contents, encoding="utf-8", newline="\n")
        configure.chmod(0o755)
        command = '\n'.join([
            'set -euo pipefail',
            'source scripts/build_common.sh',
            'source scripts/build_hardware.sh',
            'source scripts/configure_options.sh',
            'set_configure_options',
            extra,
            'check_configure_options',
            'echo "依赖编译阶段"',
        ])
        self.log = self.workdir / f"dist/logs.{platform}/configure-options.log"
        env = dict(os.environ, WORKDIR=self.workdir.as_posix(), PLATFORM=platform,
                   DIST=(self.workdir / "dist").as_posix())
        return subprocess.run([self.bash, "-c", command], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_help_is_last_and_space_containing_options_are_preserved(self):
        result = self.run_check('#!/usr/bin/env bash\nprintf "[%s]\\n" "$@"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.log.read_text(encoding="utf-8")
        self.assertTrue(log.endswith("[--help]\n"))
        self.assertIn(f"[--prefix={self.workdir.as_posix()}/stage]", log)
        self.assertIn("[--extra-cflags=-O3 -fstack-protector-strong -D_FORTIFY_SOURCE=2]", log)
        self.assertNotIn("--enable-libnfs", log)
        self.assertIn("依赖编译阶段", result.stdout)

    def test_windows_explicitly_links_external_iconv(self):
        for platform in ("linux_amd64", "win_x64"):
            with self.subTest(platform=platform):
                result = self.run_check('#!/usr/bin/env bash\nprintf "[%s]\\n" "$@"\n',
                                        platform=platform)
                self.assertEqual(result.returncode, 0, result.stderr)
                log = self.log.read_text(encoding="utf-8")
                self.assertIn("[--extra-libs=-lstdc++]", log)
                self.assertEqual("[--extra-libs=-liconv]" in log, platform == "win_x64")

    def test_unknown_option_fails_before_dependency_compilation(self):
        result = self.run_check(
            '#!/usr/bin/env bash\nfor arg; do\n'
            '  case "$arg" in\n'
            '    --enable-libnfs) echo "Unknown option --enable-libnfs"; exit 1 ;;\n'
            '    --help) exit 0 ;;\n'
            '  esac\ndone\n',
            'CONFIGURE_FLAGS+=(--enable-libnfs)',
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown option --enable-libnfs", result.stderr)
        self.assertIn("Unknown option --enable-libnfs", self.log.read_text())
        self.assertNotIn("依赖编译阶段", result.stdout)


if __name__ == "__main__":
    unittest.main()
