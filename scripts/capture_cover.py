#!/usr/bin/env python3
"""探测 DoVi/HDR 并提取 SDR 封面；需要匹配的 ffmpeg/ffprobe 与 Vulkan 驱动。"""

import argparse
import json
from pathlib import Path
import subprocess


def cover_command(ffmpeg, source, output, stream, *, seconds=60, width=1280, device="0"):
    """保留软件 HEVC 解码产生的 RPU side data，在缩放前应用 Dolby Vision。"""
    dovi = next((item for item in stream.get("side_data_list", [])
                 if item.get("side_data_type") == "DOVI configuration record"), None)
    if dovi and not dovi.get("rpu_present_flag"):
        raise ValueError("DoVi 源未声明 RPU，不能保证封面色彩正确")
    hdr = stream.get("color_transfer") in {"smpte2084", "arib-std-b67"}
    command = [ffmpeg, "-nostdin", "-hide_banner", "-v", "warning", "-n"]
    if dovi or hdr:
        command += ["-init_hw_device", f"vulkan=cover:{device}", "-filter_hw_device", "cover"]
        filters = (f"libplacebo=w={width}:h=-2:apply_dolbyvision=true:"
                   "colorspace=bt709:color_primaries=bt709:color_trc=iec61966-2-1:"
                   "range=pc:tonemapping=bt.2390,format=rgb24")
    else:
        filters = f"scale={width}:-2:flags=lanczos,format=rgb24"
    command += ["-ss", str(seconds), "-i", str(source), "-map", f"0:{stream['index']}",
                "-vf", filters, "-frames:v", "1", "-an", "-sn", "-map_metadata", "-1",
                "-update", "1"]
    if Path(output).suffix.lower() in {".jpg", ".jpeg"}:
        command += ["-q:v", "2"]
    return command + [str(output)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--device", default="0", help="Vulkan 设备序号")
    args = parser.parse_args()
    if args.seconds < 0 or args.width < 2 or args.output.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        parser.error("时间必须非负、宽度至少为 2，输出必须是 PNG/JPEG")
    if args.output.exists():
        parser.error("输出文件已存在，请指定新路径")
    info = subprocess.run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json",
                           str(args.source)], capture_output=True, check=True)
    streams = json.loads(info.stdout)["streams"]
    stream = next((s for s in streams if s.get("codec_type") == "video"
                   and not s.get("disposition", {}).get("attached_pic")), None)
    if stream is None:
        parser.error("输入没有可提取封面的视频流")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = cover_command(args.ffmpeg, args.source, args.output, stream,
                            seconds=args.seconds, width=args.width, device=args.device)
    subprocess.run(command, check=True)
    if not args.output.is_file() or args.output.stat().st_size == 0:
        raise RuntimeError("未生成封面，请检查提取时间是否超出片长")
    print(f"已生成 SDR 封面：{args.output}")


if __name__ == "__main__":
    main()
