"""单文件产物必须拒绝开发机碰巧安装的第三方 DLL。"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_windows_static as static
from prepare_windows_static import static_pc


class StaticTests(unittest.TestCase):
    def test_x265_does_not_force_shared_gcc_runtime(self):
        result = static_pc("Libs: -lx265\nLibs.private: -lstdc++ -lgcc_s -lgcc -lgcc_s -lgcc\n", "x265")
        self.assertIn("-lstdc++", result)
        self.assertNotIn("-lgcc", result)

    def test_ssh_static_dependencies_are_explicit(self):
        result = static_pc("Libs: -lssh\nRequires.private: existing\n", "libssh")
        self.assertIn("Requires.private: existing libcrypto zlib", result)
        self.assertIn("Libs.private: -liphlpapi", result)

    def test_windows_system_imports_are_allowed(self):
        names = ["KERNEL32.dll", "ucrtbase.dll", "api-ms-win-crt-runtime-l1-1-0.dll"]
        with patch.object(static, "imports", return_value=names):
            self.assertEqual(static.verify(Path("ffmpeg.exe")), sorted(names))

    def test_ssh_preserves_existing_private_libraries(self):
        result = static_pc("Libs.private: -lws2_32\n", "libssh")
        self.assertIn("Libs.private: -lws2_32 -liphlpapi", result)
        self.assertEqual(result.count("Libs.private:"), 1)
        self.assertIn("Requires.private: libcrypto zlib", result)

    def test_third_party_imports_are_rejected(self):
        for name in ("libplacebo-360.dll", "libgcc_s_seh-1.dll", "vulkan-1.dll", "msys-2.0.dll"):
            with self.subTest(name=name), patch.object(static, "imports", return_value=[name]):
                with self.assertRaisesRegex(RuntimeError, "非系统 DLL"):
                    static.verify(Path("ffmpeg.exe"))
