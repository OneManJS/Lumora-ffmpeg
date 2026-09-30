#!/usr/bin/env python3
"""验证媒体工具能力及 Lumora 使用的实际命令链，仅依赖 Python 标准库。"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def run(command, *, timeout=180, cwd=None):
    """完整读取输出，避免 pipefail 下 grep/head 提前退出导致 SIGPIPE。"""
    result = subprocess.run(command, capture_output=True, timeout=timeout, cwd=cwd)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"命令失败（{result.returncode}）：{command!r}\n{detail}")
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def listed_names(output, column):
    return {parts[column] for line in output.splitlines()
            if len(parts := line.split()) > column}


def verify_capabilities(ffmpeg, platform, allow_missing_dovi_split):
    expected = {
        "encoders": {"libx264", "aac", "mjpeg", "webvtt", "pcm_s16le", "libx265", "libsvtav1", "libxavs2"},
        "decoders": {"libdav1d", "libdavs2", "libuavs3d"},
        "filters": {"scale", "thumbnail", "silencedetect", "zscale", "tonemap"},
        "muxers": {"mp4", "matroska", "hls", "mpegts", "image2pipe", "webvtt", "chromaprint", "s16le", "null", "avs2"},
        "protocols": {"file", "pipe", "http", "https", "tls", "bluray", "sftp", "rtmp", "rtmps"},
        "bsfs": {"dovi_rpu"},
    }
    if platform.startswith("linux_"):
        expected["protocols"].update({"smb", "nfs"})
    if not allow_missing_dovi_split:
        expected["bsfs"].add("dovi_split")
    for kind, names in expected.items():
        output = run([ffmpeg, "-hide_banner", f"-{kind}"]).stdout.decode("utf-8", errors="replace")
        present = listed_names(output, 0 if kind in {"protocols", "bsfs"} else 1)
        missing = names - present
        require(not missing, f"缺少 {kind} 能力：{', '.join(sorted(missing))}")
    options = run([ffmpeg, "-hide_banner", "-h", "bsf=dovi_rpu"]).stdout
    require(b"-strip " in options, "dovi_rpu 缺少 strip 参数")


def verify_workflows(ffmpeg, ffprobe, folder):
    base = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-filter_threads", "1"]
    video = ["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=12:duration=1"]

    def encode(args):
        return run(base + [arg.as_posix() if isinstance(arg, Path) else str(arg) for arg in args], cwd=folder)

    def probe(path):
        result = run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-show_chapters", "-of", "json", path.as_posix()], cwd=folder)
        return json.loads(result.stdout)

    def check_video(path, codec, decoder=None, pixel_format=None):
        streams = probe(path).get("streams", [])
        matching = [stream for stream in streams if stream.get("codec_name") == codec]
        require(bool(matching), f"{path.name} 未探测到 {codec} 流")
        if pixel_format:
            require(matching[0].get("pix_fmt") == pixel_format, f"{path.name} 像素格式不符合预期")
        args = ["-c:v", decoder] if decoder else []
        encode(args + ["-i", path, "-map", "0:v:0", "-frames:v", "1", "-f", "null", "-"])

    print("==> 验证 H.264/AAC、ffprobe JSON、截图和 remux", flush=True)
    mp4 = folder / "out.mp4"
    encode(video + ["-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-vf", "scale=-2:'min(480,ih)'", "-c:v", "libx264", "-threads", "2",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-b:a", "128k", mp4])
    data = probe(mp4)
    require({"h264", "aac"} <= {s.get("codec_name") for s in data["streams"]}, "MP4 音视频流不完整")
    require(float(data["format"]["duration"]) > 0, "MP4 时长无效")
    require("chapters" in data, "ffprobe 未返回章节信息")
    encode(["-i", mp4, "-vf", "thumbnail=12", "-frames:v", "1", "-f", "image2pipe", "-c:v", "mjpeg", folder / "out.jpg"])
    check_video(folder / "out.jpg", "mjpeg")
    encode(["-i", mp4, "-map", "0", "-c", "copy", folder / "out.mkv"])
    check_video(folder / "out.mkv", "h264")

    print("==> 验证 HLS（MPEG-TS / fMP4）与 WebVTT", flush=True)
    for segment_type in ("mpegts", "fmp4"):
        playlist = folder / f"{segment_type}.m3u8"
        encode(["-i", mp4, "-c", "copy", "-f", "hls", "-hls_time", "1",
                "-hls_segment_type", segment_type, "-hls_list_size", "0", playlist])
        require("#EXTINF:" in playlist.read_text(), "HLS 清单未生成分片")
        check_video(playlist, "h264")
    subtitle = folder / "input.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:00,800\nLumora\n", encoding="utf-8")
    encode(["-i", subtitle, "-c:s", "webvtt", folder / "out.vtt"])
    require("Lumora" in (folder / "out.vtt").read_text(), "WebVTT 字幕内容丢失")

    print("==> 验证音频指纹、PCM 和静音检测", flush=True)
    # Chromaprint 需要足够的样本才能产生有效指纹，1 秒输入会输出空结果。
    result = encode(["-f", "lavfi", "-i", "sine=frequency=440:duration=12", "-ar", "44100", "-ac", "2",
                     "-c:a", "pcm_s16le", "-fp_format", "raw", "-f", "chromaprint", "pipe:1"])
    require(len(result.stdout) >= 4, "Chromaprint 未输出有效指纹")
    result = encode(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-ar", "2000", "-ac", "1",
                     "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1"])
    require(len(result.stdout) == 4000, "PCM 输出长度不符合 2000Hz 单声道 16bit 约定")
    result = encode(["-loglevel", "info", "-f", "lavfi", "-i", "anullsrc=duration=1",
                     "-af", "silencedetect=n=-50dB:d=0.33", "-f", "null", "-"])
    require(b"silence_start" in result.stderr, "缺少 silence_start 静音检测信息")

    print("==> 验证 HEVC 10bit、HDR tone-mapping、AV1 和 AVS2", flush=True)
    hevc = folder / "hevc.mkv"
    encode(video + ["-c:v", "libx265", "-preset", "ultrafast", "-threads", "2",
                    "-x265-params", "log-level=error:pools=2", "-pix_fmt", "yuv420p10le", hevc])
    check_video(hevc, "hevc", pixel_format="yuv420p10le")
    tone = ("format=yuv420p10le,zscale=pin=bt2020:tin=smpte2084:min=bt2020nc:rin=limited:"
            "t=linear:m=gbr:p=bt2020:r=full:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
            "zscale=t=bt709:m=bt709:r=limited,format=yuv420p")
    encode(video + ["-vf", tone, "-frames:v", "1", folder / "tone.jpg"])
    check_video(folder / "tone.jpg", "mjpeg")
    encode(video + ["-c:v", "libsvtav1", "-preset", "12", "-crf", "35", "-svtav1-params", "lp=2", folder / "av1.mkv"])
    check_video(folder / "av1.mkv", "av1", decoder="libdav1d")
    encode(video + ["-c:v", "libxavs2", "-threads", "2", "-frames:v", "3", "-f", "avs2", folder / "out.avs2"])
    check_video(folder / "out.avs2", "avs2", decoder="libdavs2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--platform", required=True, choices=("linux_amd64", "linux_arm64", "win_x64"))
    parser.add_argument("--allow-missing-dovi-split", action="store_true", help="兼容不含 dovi_split 的旧版源码")
    parser.add_argument("--checks", choices=("all", "capabilities", "workflows"), default="all", help="局部排查时选择检查范围；构建固定执行 all")
    args = parser.parse_args()
    print(run([args.ffmpeg, "-version"]).stdout.decode(errors="replace").splitlines()[0], flush=True)
    if args.checks in {"all", "capabilities"}:
        verify_capabilities(args.ffmpeg, args.platform, args.allow_missing_dovi_split)
    if args.checks in {"all", "workflows"}:
        with tempfile.TemporaryDirectory(prefix="lumora-smoke-") as directory:
            verify_workflows(args.ffmpeg, args.ffprobe, Path(directory))
    print("==> 所选验收项目全部通过", flush=True)


if __name__ == "__main__":
    main()
