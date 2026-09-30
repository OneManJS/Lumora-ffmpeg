#!/usr/bin/env python3
"""使用本地 DoVi Profile 5 实片验证 RPU 应用；不下载或上传媒体。"""

import argparse
import json
from pathlib import Path
import tempfile

from capture_cover import cover_command
from verify_media_tools import require, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--reference", type=Path, help="同时间点人工确认色彩正确的参考图")
    args = parser.parse_args()
    streams = json.loads(run([args.ffprobe, "-v", "error", "-show_streams", "-of", "json",
                              str(args.source)]).stdout)["streams"]
    video = next(s for s in streams if s.get("codec_type") == "video"
                 and not s.get("disposition", {}).get("attached_pic"))
    dovi = next((s for s in video.get("side_data_list", []) if s.get("dv_profile") == 5), None)
    require(dovi and dovi.get("rpu_present_flag"), "验收输入必须是带 RPU 的 DoVi Profile 5")

    def pixels(path):
        return run([args.ffmpeg, "-v", "error", "-i", str(path), "-vf", "scale=320:180",
                    "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]).stdout

    with tempfile.TemporaryDirectory(prefix="lumora-dovi-") as temp:
        output = Path(temp) / "cover.png"
        command = cover_command(args.ffmpeg, args.source, output, video, seconds=args.seconds)
        run(command)
        corrected = pixels(output)
        output.unlink()
        filters = command.index("-vf") + 1
        command[filters] = command[filters].replace("apply_dolbyvision=true", "apply_dolbyvision=false")
        run(command)
        ignored = pixels(output)
        require(len(corrected) == len(ignored) == 320 * 180 * 3, "封面像素尺寸异常")
        delta = sum(abs(a - b) for a, b in zip(corrected, ignored)) / len(corrected)
        require(delta > 1, "应用与忽略 RPU 的结果几乎相同，请更换测试帧或检查 DoVi 支持")
        print(f"RPU 开关平均像素差：{delta:.2f}/255")
        if args.reference:
            reference = pixels(args.reference)
            require(len(reference) == len(corrected), "参考图像素尺寸异常")
            error = sum(abs(a - b) for a, b in zip(corrected, reference)) / len(corrected)
            require(error < 8, f"封面与人工确认参考图的平均像素误差过大：{error:.2f}/255")
            print(f"参考图平均像素误差：{error:.2f}/255")
    print("DoVi Profile 5 封面验收通过；没有参考图时仅证明 RPU 生效，不代表色彩绝对准确")


if __name__ == "__main__":
    main()
