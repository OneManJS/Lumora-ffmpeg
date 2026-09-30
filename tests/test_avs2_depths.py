"""AVS2 分发边界及验收失败检测，不依赖真实媒体或网络。"""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_media", ROOT / "scripts/verify_media_tools.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

# 测试替身只声明分发器实际使用的 ABI 字段，后端实现由 C 测试提供。
HEADER = """
#include <stdint.h>
typedef struct { int threads, info_level; void *opaque; int disable_avx; } davs2_param_t;
typedef struct { const uint8_t *data; int len; int64_t pts, dts; } davs2_packet_t;
typedef struct { int unused; } davs2_seq_info_t;
typedef struct { int unused; } davs2_picture_t;
enum { DAVS2_ERROR=-1, DAVS2_DEFAULT=0, DAVS2_GOT_FRAME=1, DAVS2_GOT_HEADER=2, DAVS2_END=3 };
enum { DAVS2_PROFILE_MAIN_PIC=0x12, DAVS2_PROFILE_MAIN=0x20, DAVS2_PROFILE_MAIN10=0x22 };
"""

HARNESS = r"""
#include <assert.h>
#include "davs2_dispatch.c"

static int opened8, opened10, closed, sent;
static int64_t pts;
#define STUB(prefix, counter) \
void *prefix##davs2_decoder_open(davs2_param_t *p) { (void)p; ++counter; return &counter; } \
int prefix##davs2_decoder_send_packet(void *d, davs2_packet_t *p) \
    { (void)d; sent += p->len; pts = p->pts; return 0; } \
int prefix##davs2_decoder_recv_frame(void *d, davs2_seq_info_t *h, davs2_picture_t *f) \
    { (void)d; (void)h; (void)f; return 0; } \
int prefix##davs2_decoder_flush(void *d, davs2_seq_info_t *h, davs2_picture_t *f) \
    { (void)d; (void)h; (void)f; return DAVS2_END; } \
void prefix##davs2_decoder_frame_unref(void *d, davs2_picture_t *f) { (void)d; (void)f; } \
void prefix##davs2_decoder_close(void *d) { (void)d; ++closed; }

STUB(lumora8_, opened8)
STUB(lumora10_, opened10)

int main(void)
{
    unsigned char h8[11] = {0,0,1,0xb0,0x20,0x42,0x80,64,1,1,0x20};
    unsigned char h10[11] = {0,0,1,0xb0,0x22,0x42,0x80,64,1,1,0x48};
    davs2_param_t params = {0};
    assert(davs2_decoder_open(NULL) == NULL);
    void *eight = davs2_decoder_open(&params);
    void *ten = davs2_decoder_open(&params);
    assert(davs2_decoder_flush(ten, NULL, NULL) == DAVS2_END);
    davs2_decoder_frame_unref(ten, NULL);
    davs2_packet_t p = {h10, 6, 123, 120};
    assert(davs2_decoder_send_packet(ten, &p) == 0);
    assert(opened10 == 0);
    p.data = h10 + 6; p.len = 5; p.pts = 456;
    assert(davs2_decoder_send_packet(ten, &p) == 0);
    assert(opened10 == 1 && opened8 == 0 && sent == 11 && pts == 123);
    p.data = h8; p.len = 11;
    assert(davs2_decoder_send_packet(eight, &p) == 0);
    assert(opened8 == 1 && opened10 == 1);
    assert(davs2_decoder_send_packet(ten, &p) == DAVS2_ERROR);
    assert(davs2_decoder_recv_frame(ten, NULL, NULL) == DAVS2_ERROR);
    davs2_decoder_close(eight); davs2_decoder_close(ten);
    assert(closed == 2);
    /* 不支持的 12bit 必须报错，不能退回 8bit。 */
    ten = davs2_decoder_open(&params);
    h10[10] = 0x6c; p.data = h10;
    assert(davs2_decoder_send_packet(ten, &p) == DAVS2_ERROR);
    assert(opened10 == 1);
    davs2_decoder_close(ten);
    /* 非法包和未选后端的关闭不能崩溃。 */
    eight = davs2_decoder_open(&params);
    p.data = NULL; p.len = 5;
    assert(davs2_decoder_send_packet(eight, &p) == DAVS2_ERROR);
    p.len = -1;
    assert(davs2_decoder_send_packet(eight, &p) == DAVS2_ERROR);
    p.len = 0;
    assert(davs2_decoder_send_packet(eight, &p) == DAVS2_DEFAULT);
    davs2_decoder_close(eight); davs2_decoder_close(NULL);
    return 0;
}
"""


class Avs2DepthTests(unittest.TestCase):
    def test_dispatch_lifecycle_split_headers_and_depth_isolation(self):
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler and os.name == "nt":
            candidate = ROOT / ".tmp-media-tools-build/msys64/ucrt64/bin/gcc.exe"
            if candidate.is_file():
                compiler = str(candidate)
        if not compiler:
            self.skipTest("需要 C 编译器运行分发器边界测试")
        env = dict(os.environ)
        env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "davs2.h").write_text(HEADER, encoding="utf-8")
            (folder / "harness.c").write_text(HARNESS, encoding="utf-8")
            binary = folder / ("check.exe" if os.name == "nt" else "check")
            result = subprocess.run([compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                            "-I", str(folder), "-I", str(ROOT / "scripts"),
                            str(folder / "harness.c"), "-o", str(binary)],
                           capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=10, env=env)

    def test_gray_header_promotion_preserves_other_units(self):
        header = b"\x00\x00\x01\xb0\x20\x42\x80\x40\x01\x01\x20\x80"
        picture = b"\x00\x00\x01\xb3\xff\xff"
        result = verify.avs2_gray_main10(header + picture)
        self.assertEqual(result[4], 0x22)
        self.assertEqual(result[10] >> 2, 0x12)
        self.assertTrue(result.endswith(picture))

    def test_invalid_gray_header_is_rejected(self):
        for data in (b"", b"\x00\x00\x01\xb0\x22", b"not avs2"):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                verify.avs2_gray_main10(data)

    def test_success_exit_with_no_decoded_frames_is_rejected(self):
        header = b"\x00\x00\x01\xb0\x20\x42\x80\x40\x01\x01\x20\x80"
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)

            def empty_decode(command):
                if command[-1].endswith("gray8.avs2"):
                    Path(command[-1]).write_bytes(header)
                return subprocess.CompletedProcess(command, 0, b"", b"")

            with patch.object(verify, "run", side_effect=empty_decode):
                with self.assertRaisesRegex(RuntimeError, "帧数或像素"):
                    verify.verify_avs2_depths("ffmpeg", folder)


if __name__ == "__main__":
    unittest.main()
