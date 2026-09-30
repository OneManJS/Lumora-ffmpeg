"""验证 AVS 上游版本脚本在固定 commit 浅克隆和独立构建目录下的行为。"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]

# 保留固定版本上游脚本的补丁上下文，输出精简为版本号与源码 SHA。
AVS2_SCRIPT = """#!/bin/sh
VER_R=0
VER_SHA='not-in-git-tree'

# get version of remote origin/master and local HEAD
if [ -d .git ] && command -v git >/dev/null 2>&1 ; then
    VER_R=`git rev-list --count origin/master`
    VER_SHA=`git rev-parse HEAD | cut -c -16`
fi

printf '%s.%s %s\\n' "$API_VERSION" "$VER_R" "$VER_SHA"
"""

UAVS3D_SCRIPT = """#!/bin/bash
shell_dir=""
if [ ! -n "$1" ]; then
    shell_dir="."
else
    shell_dir=$1
fi

VER_R=`git rev-list origin/master | sort | wc -l | awk '{print $1}'`
VER_L=`git rev-list HEAD | sort | wc -l | awk '{print $1}'`
VER_SHA1=`git log -n 1 | head -n 1 | cut -d ' ' -f 2`

major_version="1"
printf '%s.2.%s %s\\n' "$major_version" "$VER_L" "$VER_SHA1"
"""


class AvsVersionTests(unittest.TestCase):
    def setUp(self):
        self.bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        if not self.bash or not Path(self.bash).exists() or not shutil.which("git"):
            self.skipTest("需要 Bash 和 Git")
        self.temp = tempfile.TemporaryDirectory(prefix="lumora avs ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.upstream = self.base / "upstream"
        self.source = self.base / "source"
        self.upstream.mkdir()
        self.git("init", "-q", "-b", "master", cwd=self.upstream)

    def git(self, *args, cwd):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                              text=True, encoding="utf-8").stdout.strip()

    def fetch(self, script):
        (self.upstream / "version.sh").write_text(script, encoding="utf-8", newline="\n")
        self.git("add", "version.sh", cwd=self.upstream)
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", "版本脚本测试", cwd=self.upstream)
        commit = self.git("rev-parse", "HEAD", cwd=self.upstream)
        env = dict(os.environ, TEST_REPO=self.upstream.as_uri(), TEST_REF=commit,
                   TEST_DEST=self.source.as_posix())
        subprocess.run([self.bash, "-c", 'set -euo pipefail; source scripts/build_common.sh; '
                        'fetch_pinned "$TEST_REPO" "$TEST_REF" "$TEST_DEST"'],
                       cwd=ROOT, env=env, check=True, capture_output=True, timeout=30)
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository", cwd=self.source), "true")
        self.assertEqual(self.git("branch", "-r", cwd=self.source), "")
        return commit

    def run_version(self, cwd, *args, **env):
        return subprocess.run([self.bash, (self.source / "version.sh").as_posix(), *args],
                              cwd=cwd, env=dict(os.environ, **env), capture_output=True,
                              text=True, encoding="utf-8", timeout=30)

    def test_avs2_shallow_versions_meet_ffmpeg_requirements(self):
        commit = self.fetch(AVS2_SCRIPT)
        before = self.run_version(self.source, API_VERSION="1.6")
        self.assertTrue(before.stdout.startswith("1.6. "), before.stdout)
        self.git("apply", str(ROOT / "scripts/patches/avs2-version.patch"), cwd=self.source)
        for api in ("1.6", "1.3"):
            with self.subTest(api=api):
                result = self.run_version(self.source, API_VERSION=api)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout.strip(), f"{api}.1 {commit[:16]}")

    def test_uavs3d_uses_source_repository_from_build_directory(self):
        commit = self.fetch(UAVS3D_SCRIPT)
        self.git("apply", str(ROOT / "scripts/patches/uavs3d-version.patch"), cwd=self.source)
        # 构建目录故意属于另一个仓库，避免仅验证没有仓库时不报错。
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "--allow-empty", "-qm", "独立构建目录", cwd=self.upstream)
        build = self.upstream / "build"
        build.mkdir()
        result = self.run_version(build, self.source.as_posix())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.strip(), f"1.2.1 {commit}")


if __name__ == "__main__":
    unittest.main()
