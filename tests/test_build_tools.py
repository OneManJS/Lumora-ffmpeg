"""构建辅助逻辑回归测试；不依赖编译器、外网或真实 DLL。"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dlls = load_script("collect_windows_dlls")
verify = load_script("verify_media_tools")


class DllClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / "ucrt64"
        self.bin = self.prefix / "bin"
        self.bin.mkdir(parents=True)
        self.system = self.root / "System32"
        self.system.mkdir()
        self.destination = self.root / "stage"

    def collect(self, graph):
        with patch.object(dlls, "imports", side_effect=lambda path: graph[path.name.lower()]):
            return dlls.collect([Path("ffmpeg.exe"), Path("ffprobe.exe")], self.prefix, self.destination, self.system)

    def test_deep_cycle_and_two_executable_roots(self):
        graph = {"ffmpeg.exe": ["LIB0.DLL"], "ffprobe.exe": ["probe.dll"]}
        for index in range(9):
            name = f"lib{index}.dll"
            (self.bin / name).write_bytes(name.encode())
            graph[name] = [f"lib{(index + 1) % 9}.dll", "KERNEL32.dll", "api-ms-win-core-file-l1-1-0.dll"]
        (self.system / "kernel32.dll").touch()
        (self.bin / "probe.dll").write_bytes(b"probe")
        graph["probe.dll"] = []
        result = self.collect(graph)
        self.assertEqual(len(result), 10)
        self.assertEqual((self.destination / "lib8.dll").read_bytes(), b"lib8.dll")
        self.assertFalse((self.destination / "kernel32.dll").exists())

    def test_missing_dependency_fails_before_copy(self):
        with self.assertRaisesRegex(RuntimeError, "missing.dll"):
            self.collect({"ffmpeg.exe": ["missing.dll"]})
        self.assertFalse(self.destination.exists())

    def test_msys_dependency_is_rejected_even_if_installed(self):
        (self.bin / "msys-2.0.dll").touch()
        with self.assertRaisesRegex(RuntimeError, "MSYS/Cygwin"):
            self.collect({"ffmpeg.exe": ["msys-2.0.dll"]})

    def test_objdump_parser(self):
        output = "DLL Name: KERNEL32.dll\n\tDLL Name: libstdc++-6.dll\n"
        with patch.object(dlls.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
            self.assertEqual(dlls.imports(Path("ffmpeg.exe")), ["KERNEL32.dll", "libstdc++-6.dll"])


class VerificationTests(unittest.TestCase):
    @staticmethod
    def capability_result(command):
        outputs = {
            "-encoders": "libx264 aac mjpeg webvtt pcm_s16le libx265 libsvtav1 libxavs2 h264_nvenc hevc_nvenc h264_vaapi hevc_vaapi h264_v4l2m2m h264_qsv hevc_qsv h264_amf hevc_amf",
            "-decoders": "libdav1d libdavs2 libuavs3d h264_cuvid hevc_cuvid h264_qsv hevc_qsv",
            "-filters": "scale thumbnail silencedetect zscale tonemap subtitles ass drawtext hwupload_cuda scale_cuda hwdownload scale_vaapi scale_qsv",
            "-muxers": "mp4 matroska hls mpegts image2pipe webvtt chromaprint s16le null avs2",
            "-protocols": "file pipe http https tls bluray sftp rtmp rtmps smb nfs",
            "-bsfs": "dovi_rpu",
            "-hwaccels": "cuda vaapi vdpau drm qsv dxva2 d3d11va d3d12va",
        }
        option = command[-1]
        if option == "bsf=dovi_rpu":
            output = "  -strip <boolean>"
        elif option in {"-protocols", "-bsfs", "-hwaccels"}:
            output = "\n".join(outputs[option].split())
        else:
            output = "\n".join(" ... " + name for name in outputs[option].split())
        return subprocess.CompletedProcess(command, 0, output.encode(), b"")

    def test_linux_protocol_uses_smb_url_name(self):
        with patch.object(verify, "run", side_effect=self.capability_result):
            verify.verify_capabilities("ffmpeg", "linux_amd64", True)

    def test_missing_hardware_encoder_is_rejected_without_gpu(self):
        def without_nvenc(command):
            result = self.capability_result(command)
            result.stdout = result.stdout.replace(b"h264_nvenc", b"disabled_nvenc")
            return result
        with patch.object(verify, "run", side_effect=without_nvenc):
            with self.assertRaisesRegex(RuntimeError, "h264_nvenc"):
                verify.verify_capabilities("ffmpeg", "win_x64", True)

    def test_arm64_does_not_require_intel_qsv(self):
        def without_qsv(command):
            result = self.capability_result(command)
            result.stdout = result.stdout.replace(b"qsv", b"not_enabled")
            return result
        with patch.object(verify, "run", side_effect=without_qsv):
            verify.verify_capabilities("ffmpeg", "linux_arm64", True)
            with self.assertRaisesRegex(RuntimeError, "qsv"):
                verify.verify_capabilities("ffmpeg", "linux_amd64", True)

    def test_missing_subtitle_filter_is_rejected(self):
        def without_subtitles(command):
            result = self.capability_result(command)
            result.stdout = result.stdout.replace(b"subtitles", b"disabled_subtitles")
            return result
        with patch.object(verify, "run", side_effect=without_subtitles):
            with self.assertRaisesRegex(RuntimeError, "subtitles"):
                verify.verify_capabilities("ffmpeg", "win_x64", True)

    def test_subtitle_rendering_must_change_pixels(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            font = folder / "input.ttf"
            font.touch()
            black = subprocess.CompletedProcess([], 0, bytes(320 * 240 * 3), b"")
            with patch.object(verify, "run", return_value=black):
                with self.assertRaisesRegex(RuntimeError, "文字未实际渲染"):
                    verify.verify_subtitles("ffmpeg", folder, font)

    def test_missing_dovi_split_requires_explicit_compatibility_flag(self):
        with patch.object(verify, "run", side_effect=self.capability_result):
            with self.assertRaisesRegex(RuntimeError, "dovi_split"):
                verify.verify_capabilities("ffmpeg", "win_x64", False)

    def test_capability_matching_uses_name_not_description(self):
        names = verify.listed_names(" V..... other libx264 encoder\n V..... libx265 HEVC", 1)
        self.assertNotIn("libx264", names)
        self.assertIn("libx265", names)

    def test_command_failure_includes_stderr(self):
        result = subprocess.CompletedProcess([], 7, b"", "缺少编码器".encode())
        with patch.object(verify.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "缺少编码器"):
                verify.run(["ffmpeg"])

    def test_command_timeout_is_not_ignored(self):
        with patch.object(verify.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                verify.run(["ffmpeg"], timeout=1)


class SourceResolutionTests(unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which("bash")
        if os.name == "nt":
            self.bash = "C:/Program Files/Git/bin/bash.exe"
        if not self.bash or not Path(self.bash).exists():
            self.skipTest("未安装 Bash")
        self.temp = tempfile.TemporaryDirectory(prefix="lumora source test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "origin"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("-c", "user.name=测试", "-c", "user.email=test@example.invalid", "commit", "-q", "--allow-empty", "-m", "测试源码")
        self.git("tag", "-a", "n9.0.2", "-m", "稳定版", config=True)
        self.git("branch", "feature/test")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args, config=False):
        command = ["git", "-C", str(self.repo)]
        if config:
            command += ["-c", "user.name=测试", "-c", "user.email=test@example.invalid"]
        return subprocess.run(command + list(args), check=True, capture_output=True, text=True, encoding="utf-8")

    def resolve(self, ref):
        output = self.root / "outputs"
        env = dict(os.environ, FFMPEG_REF=ref, FFMPEG_REPO=self.repo.as_posix(), GITHUB_OUTPUT=output.as_posix())
        result = subprocess.run([self.bash, str(ROOT / "scripts/resolve_ffmpeg.sh")], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        data = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
        return result, data

    def test_annotated_tag_resolves_to_commit(self):
        result, data = self.resolve("n9.0.2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data, {"ref": "n9.0.2", "commit": self.commit, "version": "9.0.2"})

    def test_branch_uses_commit_in_artifact_version(self):
        result, data = self.resolve("feature/test")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["version"], "g" + self.commit[:12])

    def test_exact_commit(self):
        result, data = self.resolve(self.commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["commit"], self.commit)

    def test_rejects_newline_and_shell_fragments(self):
        for ref in ("n9.0.2\nversion=bad", "$(touch injected)", "--upload-pack=bad", "../bad"):
            with self.subTest(ref=ref):
                result, data = self.resolve(ref)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(data, {})

    def test_missing_ref_fails_without_outputs(self):
        result, data = self.resolve("missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
