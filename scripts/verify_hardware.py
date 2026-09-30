#!/usr/bin/env python3
"""在部署机器上验证 GPU 编码和解码；普通托管 CI 不自动运行本脚本。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from verify_media_tools import require, run


def hardware_commands(backend, device):
    """返回设备初始化、上传滤镜、编码器及硬件解码参数。"""
    if backend == "nvenc":
        init = ["-init_hw_device", f"cuda=gpu:{device or '0'}", "-filter_hw_device", "gpu"]
        return init, "format=nv12,hwupload,scale_cuda=160:120", "h264_nvenc", [
            "-hwaccel", "cuda", "-hwaccel_device", "gpu", "-hwaccel_output_format", "cuda"]
    if backend == "vaapi":
        init = ["-init_hw_device", f"vaapi=gpu:{device or '/dev/dri/renderD128'}", "-filter_hw_device", "gpu"]
        return init, "format=nv12,hwupload,scale_vaapi=160:120", "h264_vaapi", [
            "-hwaccel", "vaapi", "-hwaccel_device", "gpu", "-hwaccel_output_format", "vaapi"]
    if backend == "qsv":
        child = (f"child_device_type=d3d11va,child_device={device or '0'}" if os.name == "nt"
                 else f"child_device={device or '/dev/dri/renderD128'}")
        init = ["-init_hw_device", f"qsv=gpu:hw,{child}", "-filter_hw_device", "gpu"]
        return init, "format=nv12,hwupload=extra_hw_frames=32,scale_qsv=160:120", "h264_qsv", [
            "-hwaccel", "qsv", "-hwaccel_device", "gpu", "-hwaccel_output_format", "qsv", "-c:v", "h264_qsv"]
    if backend == "amf":
        require(os.name == "nt", "当前 AMF 验收面向 Windows")
        init = ["-init_hw_device", f"d3d11va=gpu:{device or '0'}", "-filter_hw_device", "gpu"]
        return init, "scale=160:120,format=nv12,hwupload", "h264_amf", [
            "-hwaccel", "d3d11va", "-hwaccel_device", "gpu", "-hwaccel_output_format", "d3d11"]
    raise ValueError(f"不支持的硬件后端：{backend}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--backend", required=True, choices=("nvenc", "vaapi", "qsv", "amf"))
    parser.add_argument("--device", help="CUDA/Windows 的显卡序号，或 Linux 的 DRM 设备路径")
    args = parser.parse_args()
    executables = [shutil.which(args.ffmpeg), shutil.which(args.ffprobe)]
    require(all(executables), "找不到 ffmpeg 或 ffprobe")
    ffmpeg, ffprobe = [str(Path(path).resolve()) for path in executables]
    init, filters, encoder, decode = hardware_commands(args.backend, args.device)
    with tempfile.TemporaryDirectory(prefix="lumora-gpu-") as directory:
        path = Path(directory) / "gpu.mp4"
        base = [ffmpeg, "-nostdin", "-v", "error", "-y"] + init
        run(base + ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12:duration=1",
                    "-vf", filters, "-c:v", encoder, "-frames:v", "12", str(path)])
        data = json.loads(run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)]).stdout)
        stream = data["streams"][0]
        require((stream.get("codec_name"), stream.get("width"), stream.get("height")) == ("h264", 160, 120),
                "GPU 编码输出格式或尺寸异常")
        # 硬件帧必须下载回内存；若偷偷回退软件解码，hwdownload 会失败。
        result = run(base + decode + ["-threads", "2", "-i", str(path), "-vf", "hwdownload,format=nv12",
                                     "-frames:v", "12", "-pix_fmt", "nv12", "-f", "rawvideo", "pipe:1"])
        require(len(result.stdout) == 160 * 120 * 3 // 2 * 12, "GPU 解码帧数或尺寸异常")
    print(f"{args.backend} 硬件编码与解码验收通过")


if __name__ == "__main__":
    main()
