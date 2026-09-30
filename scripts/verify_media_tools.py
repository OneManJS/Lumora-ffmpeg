#!/usr/bin/env python3
"""验证媒体工具能力及 Lumora 使用的实际命令链，仅依赖 Python 标准库。"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
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
        "filters": {"scale", "thumbnail", "silencedetect", "zscale", "tonemap", "libplacebo", "subtitles", "ass", "drawtext"},
        "muxers": {"mp4", "matroska", "hls", "mpegts", "image2pipe", "webvtt", "chromaprint", "s16le", "null", "avs2"},
        "protocols": {"file", "pipe", "http", "https", "tls", "bluray", "sftp", "rtmp", "rtmps"},
        "bsfs": {"dovi_rpu"},
        "hwaccels": {"cuda", "vulkan"},
    }
    expected["encoders"].update({"h264_nvenc", "hevc_nvenc"})
    expected["decoders"].update({"h264_cuvid", "hevc_cuvid"})
    expected["filters"].update({"hwupload_cuda", "scale_cuda", "hwdownload"})
    if platform.startswith("linux_"):
        expected["protocols"].add("smb")
        expected["hwaccels"].update({"vaapi", "vdpau", "drm"})
        expected["encoders"].update({"h264_vaapi", "hevc_vaapi", "h264_v4l2m2m"})
        expected["filters"].add("scale_vaapi")
    if platform in {"linux_amd64", "win_x64"}:
        expected["hwaccels"].add("qsv")
        expected["encoders"].update({"h264_qsv", "hevc_qsv"})
        expected["decoders"].update({"h264_qsv", "hevc_qsv"})
        expected["filters"].add("scale_qsv")
    if platform == "win_x64":
        expected["hwaccels"].update({"dxva2", "d3d11va", "d3d12va"})
        expected["encoders"].update({"h264_amf", "hevc_amf"})
    if not allow_missing_dovi_split:
        expected["bsfs"].add("dovi_split")
    for kind, names in expected.items():
        output = run([ffmpeg, "-hide_banner", f"-{kind}"]).stdout.decode("utf-8", errors="replace")
        present = listed_names(output, 0 if kind in {"protocols", "bsfs", "hwaccels"} else 1)
        missing = names - present
        require(not missing, f"缺少 {kind} 能力：{', '.join(sorted(missing))}")
    options = run([ffmpeg, "-hide_banner", "-h", "bsf=dovi_rpu"]).stdout
    require(b"-strip " in options, "dovi_rpu 缺少 strip 参数")
    options = run([ffmpeg, "-hide_banner", "-h", "filter=libplacebo"]).stdout
    require(b"apply_dolbyvision" in options, "libplacebo 缺少 Dolby Vision 应用选项")


def verify_subtitles(ffmpeg, folder, font=None):
    if font is None:
        font = (Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "Fonts/arial.ttf"
                if os.name == "nt" else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
    require(font.is_file(), f"找不到验收字体：{font}，请通过 --font 指定 TTF 字体")
    shutil.copy2(font, folder / "font.ttf")
    (folder / "burn.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nLumora\n", encoding="utf-8")
    (folder / "burn.ass").write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,10,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\i1}Lumora{\\i0}\n", encoding="utf-8")
    base = [ffmpeg, "-nostdin", "-v", "error", "-filter_threads", "1", "-f", "lavfi",
            "-i", "color=black:size=320x240:rate=1:duration=1"]
    output = ["-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    plain = run(base + output, cwd=folder).stdout
    require(len(plain) == 320 * 240 * 3, "字幕验收基准帧尺寸异常")
    for expression in ("subtitles=burn.srt:fontsdir=.", "ass=burn.ass:fontsdir=.",
                       "drawtext=fontfile=font.ttf:text=Lumora:fontsize=28:fontcolor=white:x=10:y=10"):
        rendered = run(base + ["-vf", expression] + output, cwd=folder).stdout
        require(len(rendered) == len(plain) and rendered != plain, f"文字未实际渲染：{expression}")


def avs2_gray_main10(data):
    """将无残差中性灰测试流的序列头改为 Main10，预测中值由 128 变为 512。

    仅用于本脚本生成的恒定灰色全帧内样本，不能用于转换普通 AVS2 视频。
    """
    starts = [match.start() for match in re.finditer(b"\x00\x00\x01", data)] + [len(data)]
    parts = []
    headers = 0
    for start, end in zip(starts, starts[1:]):
        part = data[start:end]
        if len(part) > 4 and part[3] == 0xb0:
            bits = "".join(f"{value:08b}" for value in part[4:])
            require(len(bits) >= 51 and bits[:8] == "00100000" and bits[48:51] == "001",
                    "AVS2 灰色测试样本序列头异常")
            bits = "00100010" + bits[8:48] + "010010" + bits[51:]
            bits += "0" * (-len(bits) % 8)
            part = part[:4] + bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))
            headers += 1
        parts.append(part)
    require(headers > 0, "AVS2 灰色测试样本缺少序列头")
    return b"".join(parts)


def verify_avs2_depths(ffmpeg, folder):
    """验证真实帧数、逐像素结果和同进程混合位深，不以退出码代替解码成功。"""
    base = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y"]
    gray8 = bytes([128]) * (64 * 64 * 3 // 2) * 3
    gray10 = b"\x00\x02" * (64 * 64 * 3 // 2) * 3
    raw = folder / "gray.yuv"
    raw.write_bytes(gray8)
    stream8 = folder / "gray8.avs2"
    stream10 = folder / "gray10.avs2"
    run(base + ["-f", "rawvideo", "-pixel_format", "yuv420p", "-video_size", "64x64",
                "-framerate", "25", "-i", str(raw), "-c:v", "libxavs2", "-threads", "1",
                "-xavs2-params", "IntraPeriodMin=1:IntraPeriodMax=1", "-f", "avs2", str(stream8)])
    stream10.write_bytes(avs2_gray_main10(stream8.read_bytes()))
    for depth, stream, pixel, expected in (
        (8, stream8, "yuv420p", gray8), (10, stream10, "yuv420p10le", gray10)
    ):
        result = run(base + ["-threads", "2", "-i", str(stream), "-map", "0:v:0",
                             "-pix_fmt", pixel, "-f", "rawvideo", "pipe:1"])
        require(result.stdout == expected, f"AVS2 {depth}bit 解码帧数或像素不正确")
        require(b"error" not in result.stderr.lower(), f"AVS2 {depth}bit 测试流出现解码错误")
    # 两个后端同时活动时也必须与各自的独立解码结果一致。
    mixed8, mixed10 = folder / "mixed8.yuv", folder / "mixed10.yuv"
    run(base + ["-threads", "2", "-i", str(stream8), "-threads", "2", "-i", str(stream10),
                "-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo", str(mixed8),
                "-map", "1:v:0", "-pix_fmt", "yuv420p10le", "-f", "rawvideo", str(mixed10)])
    require(mixed8.read_bytes() == gray8 and mixed10.read_bytes() == gray10,
            "AVS2 混合位深解码发生像素串扰")


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
    print("==> 验证 AVS2 8bit/10bit 完整像素及同进程混合解码", flush=True)
    verify_avs2_depths(ffmpeg, folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--platform", required=True, choices=("linux_amd64", "linux_arm64", "win_x64"))
    parser.add_argument("--allow-missing-dovi-split", action="store_true", help="兼容不含 dovi_split 的旧版源码")
    parser.add_argument("--checks", choices=("all", "capabilities", "workflows", "subtitles"), default="all", help="局部排查时选择检查范围；构建固定执行 all")
    parser.add_argument("--font", type=Path, help="字幕烧录验收使用的 TTF 字体")
    args = parser.parse_args()
    print(run([args.ffmpeg, "-version"]).stdout.decode(errors="replace").splitlines()[0], flush=True)
    if args.checks in {"all", "capabilities"}:
        verify_capabilities(args.ffmpeg, args.platform, args.allow_missing_dovi_split)
    if args.checks in {"all", "workflows", "subtitles"}:
        with tempfile.TemporaryDirectory(prefix="lumora-smoke-") as directory:
            if args.checks in {"all", "workflows"}:
                verify_workflows(args.ffmpeg, args.ffprobe, Path(directory))
            print("==> 验证 SRT/ASS 字幕烧录与 drawtext 实际像素", flush=True)
            verify_subtitles(args.ffmpeg, Path(directory), args.font)
    print("==> 所选验收项目全部通过", flush=True)


if __name__ == "__main__":
    main()
