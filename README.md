# Lumora-ffmpeg

[Lumora（拾光 · Lumora）](../Lumora) 专用的 ffmpeg / ffprobe 自建发行版：以 GitHub Actions 从上游官方源码按需构建，在**性能、能力、安全**三者间取平衡，产物布局与 Lumora 的 `media-tools/` vendored zip 约定兼容。

- 产物平台：`linux_amd64`、`linux_arm64`（debian bookworm 动态链接）、`win_x64`（MSYS2 UCRT64，自包含 dll）
- 构建入口：`.github/workflows/build.yml`（手动 dispatch 可选发布 Release；**每周一自动检查并同步上游最新稳定版**），默认基于 **FFmpeg 9.x**（含 `dovi_split`）
- 构建脚本：`scripts/build_media_tools.sh`（Linux）、`scripts/build_media_tools_win.sh`（Windows）
- 硬件加速：NVIDIA NVENC/NVDEC + CUDA；Linux VAAPI/VDPAU/DRM/V4L2 M2M；x64 Intel QSV；Windows AMF/DXVA2/D3D11VA/D3D12VA
- 字幕：WebVTT 输出、libass 的 SRT/ASS/SSA 烧录、FreeType/HarfBuzz 的 drawtext，支持字体发现与文字整形
- 高级编码：HEVC（libx265）、AV1（libsvtav1）、HDR/DoVi 管线（libzimg + `zscale`/`tonemap`、`dovi_rpu`/`dovi_split`）
- 国产编码：AVS2 编/解码（libxavs2 / libdavs2）、AVS3 解码（libuavs3d），源码编译静态链入
- 体积以实际 Release 为准：保留内置解码器和滤镜，Windows 还包含动态依赖，不承诺固定的压缩包大小

## 1. 背景与动机

Lumora 此前直接 vendored 第三方（jellyfin-ffmpeg 8.1.2）构建，三平台 zip 合计约 148 MB 进 git 仓库，存在四类问题：

1. **依赖范围**：需要明确区分硬件转码、字幕渲染等必要能力与 OCR、桌面采集等可选组件，不能单纯按体积裁掉功能；
2. **版本被动**：升级依赖上游发布节奏，安全补丁无法自主跟进；
3. **能力不透明**：`--enable` 清单黑盒，行为差异只能靠运行时踩坑发现；
4. **供应链不可控**：无法回答"这个二进制从哪份源码、哪些依赖、什么参数构建而来"。

本仓库将构建过程白盒化：FFmpeg ref 在 CI 中统一解析为 commit，三平台使用同一源码；AVS 依赖固定 commit，能力验收以脚本固化。构建记录包含实际 commit、软件包版本和配置，但 apt/MSYS2 软件仓库会更新，因此当前不保证跨时间逐字节复现。

## 2. 设计原则：性能 / 能力 / 安全的取舍

| 维度 | 策略 | 说明 |
| --- | --- | --- |
| 能力 | **保留软件处理、硬件转码及字幕渲染** | 保留内置媒体处理能力，显式启用各平台的 GPU 后端、libass、字体与高级编码依赖；软件编码仍可由调用方选择，GPU 初始化失败不能视作构建不支持 |
| 性能 | `-O3` + nasm 汇编 + 运行时分发 | ffmpeg/x264/dav1d 的 x86 SIMD 全部是运行时 CPU dispatch，**无需 `-march=x86-64-v3` 也能拿到目标机全部向量指令**，同时保持产物通用可分发 |
| 安全 | 显式依赖 + 源码 pin + 编译加固 | `--disable-autodetect` 确保只有显式 `--enable` 的库进入链接；FFmpeg 和 AVS 源码锁定 commit；其他依赖由 Debian bookworm / MSYS2 提供，实际包版本记录在构建信息中 |

硬件加速和字幕渲染均属于构建的功能范围。能力裁剪必须依据实际需求；启用 GPU 后端后还要跟踪对应的驱动与运行库更新。构建支持某项能力不会自动改变消费侧的编码器选择或字幕处理方式。

## 3. 能力承诺清单

以下能力**必须**出现在产物中，共用验收脚本 `scripts/verify_media_tools.py` 检查能力并执行主要转码链，任何一条失败即中止、不出产物。普通 CI 检查 GPU 后端的编译注册，实机硬件验收使用 `scripts/verify_hardware.py`。网络协议、蓝光、DoVi 和 AVS3 当前检查能力注册，其中 DoVi 还检查 `strip` 参数；没有真实媒体样本的项目不代表已完成内容正确性验收。右列的消费代码路径为对接参考，本仓库不包含对应应用源码。

| 能力 | 用途（Lumora 代码依据） |
| --- | --- |
| `libx264` encoder | HLS / 浏览器 MP4 转码（`app/services/streaming/transcoding.py`、`streaming/__init__.py`） |
| `aac` encoder | 转码音轨（同上） |
| `mjpeg` encoder + `thumbnail` filter | 封面截图 / 内嵌封面提取（`app/services/media/images/capture.py`） |
| `webvtt` encoder | 字幕转 VTT（`app/services/streaming/subtitles.py`） |
| `subtitles` / `ass` filters（libass） | SRT、ASS/SSA 字幕烧录，保留 ASS 排版及样式；客户端不能原样呈现字幕时可用 |
| `drawtext` filter | 字体渲染、文字叠加，显式启用 FreeType / HarfBuzz / Fontconfig / FriBidi |
| GPU 后端、硬件编码器与缩放滤镜 | 平台能力见 3.3 节；实际可用性取决于显卡、驱动与设备访问权限 |
| `scale` filter | 转码档 480p/720p/1080p/2160p（`transcoding.py`） |
| `silencedetect` filter（stderr `silence_start` 文案） | 片头片尾边界细化（`app/services/markers/detection.py`） |
| `chromaprint` muxer（`-fp_format raw`） | 片头片尾指纹主路径，缺库时有 PCM 回退（同上） |
| `pcm_s16le` raw 输出（`-f s16le -ar 2000 -ac 1`） | 指纹通用回退路径（同上） |
| `bluray:` 协议（libbluray，含 `-playlist`） | ISO/BDMV 原盘（`app/services/media/disc/capability.py` 以 `-protocols` 探测） |
| `smb` / `nfs` / `sftp` / `rtmp(s)` 协议库 | `.strm` 透传协议白名单（`streaming/__init__.py`），缺失时仅对应源类型失败 |
| `http(s)` 协议 + reconnect / `-user_agent` | 网盘直链远程源（`transcoding.py`、`cloud_drive/analysis_usage.py`） |
| `libdav1d` | AV1 输入解码（原生解码器过慢） |
| `libx265` encoder（10/12bit） | HEVC 高效输出，HDR/DoVi 管线载体（前瞻需求） |
| `libsvtav1` encoder | AV1 高效输出（前瞻需求） |
| `zscale` filter（libzimg）+ `tonemap` filter | HDR10/HLG → SDR 色彩转换与 tone-mapping，10bit 管线（前瞻需求） |
| `dovi_rpu` / `dovi_split` bsf | DoVi RPU 剥离/透传；P7 双层拆分（后者需 FFmpeg 9.0+） |
| `libxavs2` encoder / `libdavs2` decoder | 国产 AVS2 编码与解码（见 3.2 节） |
| `libuavs3d` decoder | 国产 AVS3 解码（见 3.2 节） |
| muxer：`matroska` / `mp4`(fMP4) / `hls`+MPEG-TS / `image2pipe` / `webvtt` / `chromaprint` / `null` / raw | remux、HLS、抽帧、字幕、指纹 |
| `ffprobe -of json`（`-show_format -show_streams -show_chapters`） | 全部媒体探测路径 |

### 3.1 高级编码与杜比视界（DoVi / HDR）

针对消费方媒体库中高码率 HEVC 原盘与 WEB-DL 的完整消费路径：

| 场景 | 能力路径 |
| --- | --- |
| DoVi 直通播放 | `-c copy` remux 完整保留 RPU/EL，交给支持 DoVi 的客户端（消费方原生客户端走 libmpv） |
| DoVi P8.1 → HDR10 | HDR10 兼容的 P8.1 基层可用 `-bsf:v dovi_rpu=strip=1` 剥离 RPU，再按需求 remux 或转码；其他 P8 子类型不能一概视为 HDR10，静态 HDR 元数据需要单独保留 |
| DoVi P7 拆层 | `dovi_split` bsf（FFmpeg 9.0+）从双层流提取基层得到标准 HEVC——默认构建 ref 因此选 9.x |
| HDR10 / HLG → SDR 转码 | `zscale`（libzimg）做色彩科学转换 + `tonemap` 曲线映射，全程 10bit 管线到输出端降 8bit |
| HEVC / AV1 高效输出 | libx265（广播级压缩效率）、libsvtav1（当前最快的生产级 AV1 编码器） |
| Atmos / TrueHD / DTS:X | 解码器原生包含；对象元数据随 `-c copy` 直通完整保留，无需专门编码器 |

边界：DoVi RPU 的**编辑/注入/生成**属于 dovi_tool（libdovi）生态，本构建不集成该工具；libplacebo/Vulkan/OpenCL 的 GPU 滤镜目前未纳入依赖范围，HDR 验收使用 zimg/tonemap CPU 路径，不能据此推断整条硬件转码链都支持 GPU tone-mapping；`libfdk-aac` 因需 `--enable-nonfree`（产物不可再分发）不启用。

版本提示：FFmpeg 9 起对 https 源默认开启 TLS 证书校验（`tls_verify=1`），使用自签证书的媒体源会失败；主流网盘/CDN 直链不受影响。若必须回退 8.x（无 `dovi_split`），dispatch 时改 `ffmpeg_ref` 即可，验收门按源码中是否存在 `dovi_split` 实现决定该检查项，不依赖可变的版本字符串。

### 3.2 国产 AVS 系列（AVS2 / AVS3）

面向广电/超高清内容（CCTV 4K/8K、IPTV 等 AVS2/AVS3 编码源）的播放与入库：

| 标准 | 能力 | 来源（ffmpeg 官方文档登记仓库） |
| --- | --- | --- |
| AVS2（IEEE 1857.4 / GB/T 33475.2） | 编码 `libxavs2` + 解码 `libdavs2` | [pkuvcl/xavs2](https://github.com/pkuvcl/xavs2)、[pkuvcl/davs2](https://github.com/pkuvcl/davs2)（北大 VCL） |
| AVS3（IEEE 1857.10） | 解码 `libuavs3d` | [uavs3/uavs3d](https://github.com/uavs3/uavs3d)（ARM64 鲲鹏已验证） |

构建模型与 apt 库不同：**发行版不打包这三个库**，脚本按 commit pin（2026-09-30 基线，可用 `DAVS2_REF` / `XAVS2_REF` / `UAVS3D_REF` 环境变量覆盖）从源码编译并**静态链入** ffmpeg——运行镜像**不需要**因国产编码新增任何库，Dockerfile 集成清单不变。

已知边界（有意选择，写透明）：

- **8bit 主线**：uavs3d 的 8bit/10bit 是两套编译产物（`COMPILE_10BIT`），本构建取 8bit（网络流通内容主体）；AVS3 10bit 超高清广播源如成需求，改脚本变量重建即可；
- **AVS3 编码不在内**：开源生态无可集成进 ffmpeg 的 AVS3 编码器（广电编码器均为商业实现）；
- **arm64 上 davs2/xavs2 走 C 实现**（`--disable-asm`，上游 NEON 未完成）；uavs3d 在 arm64 有 NEON 优化；
- AVS1/AVS+ 走 ffmpeg 原生 `cavs` 解码器，无需外部库。

### 3.3 硬件加速与部署

| 平台 | 编译启用的后端 | 验收要求 |
| --- | --- | --- |
| `linux_amd64` | NVENC/NVDEC/CUVID、CUDA 滤镜、VAAPI、VDPAU、DRM、V4L2 M2M、oneVPL/QSV | H.264/HEVC NVENC、VAAPI、QSV 编码器；CUDA/VAAPI/QSV 缩放；对应解码能力 |
| `linux_arm64` | NVENC/NVDEC/CUVID、CUDA 滤镜、VAAPI、VDPAU、DRM、V4L2 M2M | 不依赖 Intel QSV；是否可用取决于 ARM 平台的驱动，通用接口不等于已支持 Jetson/RKMPP 等厂商专用栈 |
| `win_x64` | NVENC/NVDEC/CUVID、CUDA 滤镜、oneVPL/QSV、AMF、DXVA2、D3D11VA、D3D12VA | H.264/HEVC NVENC、QSV、AMF 编码器；CUDA/QSV 缩放；Windows 硬件解码后端 |

`nv-codec-headers` 默认固定版本 `n12.1.14.0`，可用 `NVCODEC_REF` 覆盖，实际 commit 写入构建记录。该版本要求 NVIDIA 驱动至少 Linux 530.41.03 / Windows 531.61；编译只安装头文件并使用 Clang 编译 CUDA 滤镜，不安装 CUDA Toolkit，也不需要构建机器有 GPU。升级头文件可能提高最低驱动要求。

Intel/AMD Linux 部署需安装匹配显卡的 VAAPI 驱动（如 `intel-media-va-driver` 或 `mesa-va-drivers`）；QSV 除 oneVPL 分发库外，还需要匹配设备的 Intel 运行时。容器需透传 `/dev/dri` 并授予渲染设备访问权限。NVIDIA 容器需宿主驱动、NVIDIA Container Toolkit、GPU 透传及 `video,compute,utility` 驱动能力；这些驱动不打包进 zip。

AV1 硬件编码、HEVC 10bit 等能力随 GPU 代际变化，不能仅凭编码器出现在 `-encoders` 中判断显卡支持。消费侧应探测设备并选择编码器，硬件不可用时按业务策略选择软件编码。

### 3.4 字幕与字体

外挂字幕、字幕转 WebVTT 和字幕烧录是不同能力。转 WebVTT 不需要 libass，但 ASS/SSA 的排版、字体、描边、动画等样式不能靠 WebVTT 完整保留；客户端无法显示时，需要服务端烧录。因此构建默认启用 libass 的 `subtitles` / `ass` 滤镜，同时启用 `drawtext`。

字体文件仍属于运行环境：Linux 镜像建议安装 `fonts-dejavu-core` 和 `fonts-noto-cjk`；Windows 的 libass 可通过 DirectWrite 使用系统字体，`drawtext` 建议指定 `fontfile`，自带字幕字体可通过 `fontsdir` 提供。zip 不包含商业字体或固定的 Fontconfig 系统配置。验收用可定位的 TTF 字体，检查 SRT/ASS 烧录和 drawtext 输出像素确实发生变化；需要单独覆盖中文字体或特殊排版时，应补充对应字体及样本。

字幕烧录通常在 CPU 上执行，连接 GPU 帧时需要按链路配置 `hwdownload`、像素格式转换、字幕滤镜及 `hwupload`，不能把 CPU 字幕滤镜直接接到 GPU 帧上。

**当前不包含的可选组件**：`ffplay`、doc、debug 符号、Vulkan/OpenCL/libplacebo 滤镜、libaom、libvpx、libvmaf、tesseract/OCR、X11/GL/pulse/jack 桌面组件。此清单不代表项目永远不需要这些能力；新增时同步调整构建依赖与验收。

## 4. 构建配置

### 4.1 Linux（debian bookworm，动态链接）

```bash
./configure \
    --prefix=<stage> \
    --disable-autodetect --disable-shared --enable-static \
    --disable-debug --disable-doc --disable-ffplay \
    --enable-ffnvcodec --enable-nvenc --enable-nvdec --enable-cuvid --enable-cuda-llvm \
    --enable-vaapi --enable-vdpau --enable-libdrm --enable-v4l2-m2m \
    --disable-vulkan --disable-opencl \
    --enable-gpl --enable-version3 --enable-libx264 --enable-libx265 \
    --enable-libsvtav1 \
    --enable-libzimg \
    --enable-libdavs2 --enable-libxavs2 --enable-libuavs3d \
    --enable-libdav1d \
    --enable-libbluray \
    --enable-chromaprint \
    --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz --enable-libfribidi \
    --enable-libsmbclient --enable-libnfs --enable-libssh --enable-librtmp \
    --enable-gnutls --enable-zlib --enable-iconv \
    --extra-cflags="-O3 -fstack-protector-strong -D_FORTIFY_SOURCE=2" \
    --extra-ldflags="-Wl,-z,relro,-z,now" --extra-libs="-lstdc++"
```

要点：

- amd64 另外传入 `--enable-libvpl` 并安装 `libvpl-dev`；arm64 不启用 QSV。完整平台参数由 `scripts/build_hardware.sh` 提供。
- `--disable-autodetect`：可复现性的关键。外部库不再按环境自动探测，只有上面显式 `--enable` 的一组进入链接；`zlib`/`iconv` 也因此显式声明（MKV 压缩头、字幕字符集转换依赖）。
- `--enable-gpl --enable-version3`：Linux 的 `libsmbclient` 需要 GPLv3，两个平台统一按 GPLv3 构建，**不得再以 LGPL 形态再分发**。发布二进制时应满足对应许可证及源码提供义务。
- HTTPS 显式启用 GnuTLS；仅启用 `librtmp` 或安装 TLS 库不会在 `--disable-autodetect` 下自动提供 HTTPS。
- 高级编码三件套：libx265（HEVC）、libsvtav1（AV1）、libzimg（`zscale`）；DoVi 处理（`dovi_rpu` / `dovi_split`）是 FFmpeg 原生 bsf，不引入外部库。
- 国产 AVS 三件套（libdavs2 / libxavs2 / libuavs3d）为源码编译依赖（见 3.2 节），构建时经 `PKG_CONFIG_PATH` 注入，**静态链入**产物。
- 编译加固：stack canary + FORTIFY + full RELRO（bookworm gcc 默认 PIE）。
- 构建依赖（`-dev` 包）与运行库同源于 bookworm，soname 天然一致；`libxml2` 等 libbluray 的传递依赖由 apt 自动解析。

### 4.2 Windows（MSYS2 UCRT64，自包含）

同 Linux 主体（含 libx265 / libsvtav1 / libzimg、DoVi bsf 与国产 AVS 三件套），差异：

- 去掉 `libsmbclient` / `libnfs` / `librtmp`（Windows 本地开发经 UNC 路径 `\\server\share` 即可访问共享；`.strm` 中 smb/nfs 协议在 Windows 开发机上不支持，属已知取舍）；
- 链接加固换成 PE 形态：`-Wl,--dynamicbase,--nxcompat`（ASLR / DEP）；
- HTTPS/TLS 显式启用 Windows SChannel；RTMP/RTMPS 使用 FFmpeg 内置实现，不依赖 `librtmp`；
- 使用 QSV/AMF/NVIDIA 和 Windows D3D/DXVA 后端，不链接 Linux VAAPI/VDPAU/DRM；显卡驱动仍由操作系统安装；
- 使用 `objdump` 的 PE 导入表递归收集 UCRT64 DLL，遍历至完整闭包；缺失 DLL 或意外依赖 MSYS/Cygwin 时构建失败。验收时从 PATH 移除 UCRT64，确认程序使用随包 DLL，两个 zip 均包含完整依赖。

### 4.3 产物布局

```
dist/
├── ffmpeg_<版本>_<平台>.zip     # Linux：平铺单文件 ffmpeg（对齐 Dockerfile `unzip -p ... ffmpeg`）
├── ffprobe_<版本>_<平台>.zip    # Windows：exe + 全部运行 dll，两个 zip 各自自包含
├── SHA256SUMS.<平台>.txt
├── config.<平台>.log            # configure 全量输出留档
└── build-info.<平台>.txt        # FFmpeg/AVS/NVIDIA 头文件 commit、软件包版本及动态依赖
```

## 5. CI 使用

`Actions → build → Run workflow`：

| 输入 | 说明 |
| --- | --- |
| `ffmpeg_ref` | 上游 [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) 的 tag（默认 `n9.0.2`，以上游实际发布的最新点版本为准）/ branch / commit，源码浅取并 detach 到该 ref。注意 `dovi_split` 需 9.0+ |
| `publish` | 勾选后，三平台验收全部通过时以 `gh release create` 发布 `media-tools-<版本>`，附件含全部 zip 与合并 `SHA256SUMS.txt` |

**自动同步官方最新稳定版**：每周一 10:00（北京时间）schedule 触发 `resolve` job，解析上游稳定 tag 并锁定 commit。对应的 `media-tools-<版本>` Release 尚未发布时构建三平台并发布，已发布则跳过；查询 API 故障会报错。major 跳跃也会被跟进，仍需关注上游兼容性变化；GitHub 对 60 天无提交的仓库自动暂停 schedule。

手动构建只解析指定 ref，不依赖“最新 tag”查询。稳定 tag 的版本名如 `9.0.2`；branch/commit 统一使用 `g<12位commit>`，zip 文件名与 Release tag 使用同一版本值。发布前检查三平台文件齐全、commit 一致，并校验包含配置和构建信息在内的 SHA256。

push / pull request 自动执行 Bash 语法检查、ShellCheck 和 Python 回归测试；完整三平台编译只在手动或定时触发时执行。所有编译任务保留构建日志，失败时仍上传可获得的 configure 诊断日志。

- Linux job 在 `debian:bookworm` 容器内构建；arm64 使用 GitHub 托管 arm runner（**公共仓库免费**；私有仓库不可用时改回 `ubuntu-latest` + QEMU，纯编译负载耗时约 3~5 倍）。
- 各 job 仅 `contents: read`，resolve 的查重与 release 发布才持有相应权限；发布走 runner 预装 `gh` CLI，不引入第三方 release action。
- 供应链加固建议（未默认做，见第 8 节）：对 `actions/*@v4`、`msys2/setup-msys2@v2` 改为完整 commit SHA pin。

### 5.1 本地构建与检查

Linux 在 Debian bookworm 原生环境以 root 执行（脚本安装 apt 依赖）；arm64 必须使用对应架构机器：

```bash
FFMPEG_REF=n9.0.2 PLATFORM=linux_amd64 JOBS=4 bash scripts/build_media_tools.sh
```

Windows 在 MSYS2 UCRT64 终端安装工作流中列出的软件包，再执行：

```bash
FFMPEG_REF=n9.0.2 JOBS=4 bash scripts/build_media_tools_win.sh
```

`JOBS` 限制编译并行度；`WORKDIR` 指定工作根目录，每次创建独立子目录，避免旧对象和 DLL 污染。`DIST` 指定输出目录，两者均可使用相对路径。构建目录会保留供排错，需要时自行清理旧目录。`FFMPEG_COMMIT` / `FFMPEG_VERSION` 由 CI 统一传入，本地通常无需设置。

无需重新编译即可检查脚本或验收已安装的工具：

```bash
shellcheck -x scripts/*.sh
python3 -m unittest discover -s tests -v
python3 scripts/verify_media_tools.py --platform win_x64 --ffmpeg /path/to/ffmpeg.exe --ffprobe /path/to/ffprobe.exe
```

旧版工具无 `dovi_split` 时加 `--allow-missing-dovi-split`；局部排错可选 `--checks capabilities`、`--checks workflows` 或 `--checks subtitles`，正式构建始终执行全部验收。验收覆盖主要软件转码链、SRT/ASS 烧录、drawtext 像素检查及平台 GPU 编译能力，临时媒体自动清理。字幕测试可通过 `--font /path/to/font.ttf` 指定字体。

在部署机器上运行 GPU 实机验收（不在普通托管 CI 中执行）：

```bash
python3 scripts/verify_hardware.py --backend nvenc
python3 scripts/verify_hardware.py --backend vaapi --device /dev/dri/renderD128
python3 scripts/verify_hardware.py --backend qsv
python3 scripts/verify_hardware.py --backend amf
```

只执行与当前设备匹配的后端，可用 `--ffmpeg` / `--ffprobe` 指定新构建的程序。验收执行 H.264 硬件编码、输出探测和硬件解码，并检查下载后的帧数；NVIDIA/VAAPI/QSV 还执行 GPU 缩放。无设备、缺驱动或发生软件解码回退时会失败，不以“跳过”冒充通过。

## 6. 集成回 Lumora

一次性切换步骤：

1. 推送本仓库到 GitHub 并跑一次 `build`（默认 `n9.0.2`，勾选 `publish=true`）；
2. 下载 Release 资产，校验 `SHA256SUMS.txt`；
3. 放入 Lumora 仓库并去掉文件名中的平台后缀（目录即平台）：
   - `ffmpeg_9.0.2_linux_amd64.zip` → `media-tools/linux_amd64/ffmpeg_9.0.2.zip`
   - 其余平台同理（`win_x64` 的两个 zip 解压到同一目录后使用）；
4. **修改 Lumora `Dockerfile` runtime 阶段的 apt 安装行**（Linux 产物是动态链接，运行库需进镜像；传递依赖由 apt 解析；`libsvtav1enc1` 在 bookworm 为 soname 1，trixie 起为 `libsvtav1enc8`）：
   ```dockerfile
   apt-get install -y --no-install-recommends ca-certificates curl nginx tini tzdata util-linux \
       libx264-164 libx265-199 libsvtav1enc1 libzimg2 libdav1d6 libbluray2 libchromaprint1 \
       libsmbclient libnfs13 libssh-4 librtmp1 libgnutls30 zlib1g libstdc++6 \
       libva2 libva-drm2 libvdpau1 libdrm2 \
       libass9 libfreetype6 libfontconfig1 libharfbuzz0b libfribidi0 fontconfig \
       fonts-dejavu-core fonts-noto-cjk
   ```
   amd64 产物还需安装 `libvpl2`，arm64 不需要。上述清单是程序动态库及字体依赖，显卡驱动和容器透传另外按 3.3 节配置。
5. `git rm` 旧的 jellyfin zip（git 历史中的 ~148 MB 需 `git filter-repo` 才真正移除，属于可选的仓库瘦身）；
6. 重跑 `docker-publish` 并在实例上验证：播放转码、封面截图、片头片尾检测、ISO 原盘探测。

集成兼容性已核对过的点：

- zip 平铺布局与 `Dockerfile` 的 `unzip -p /tmp/ffmpeg.zip ffmpeg` 约定一致；
- 不在 Dockerfile 中执行目标架构二进制（遵守 Lumora `tests/integration/test_deployment_configuration.py` 的跨架构构建约束；能力验证在本仓库 CI 的原生架构 runner 上完成）；
- `silence_start` stderr 文案、`-protocols` 输出中的 `bluray`、ffprobe JSON 结构均来自 FFmpeg/libbluray 原生行为，消费方解析逻辑无需改动；
- 片头指纹缓存键包含 `ffmpeg_path`、HLS 转码缓存键含 `"h264-aac-v3"` 标签——路径与编码行为不变则无需 bump。

## 7. 维护与安全响应

| 场景 | 动作 |
| --- | --- |
| FFmpeg 上游新稳定版 / 安全更新 | **自动**：每周一 schedule 检测并构建发布（见第 5 节）；手动路径则 dispatch 指定 ref。随后按第 6 节替换 zip |
| 外部库 CVE（x264/x265/svt-av1/zimg/dav1d/bluray/samba/ssh/rtmp…） | Linux 侧通常**无需重建**：运行库来自 bookworm，`apt` 升级即修补；Windows 侧需重跑 MSYS2 构建 |
| AVS 库更新 | 用 `DAVS2_REF` / `XAVS2_REF` / `UAVS3D_REF` 环境变量（或改脚本默认值）指定新 commit 重建；静态链入，更新只能经重建生效 |
| GPU 后端更新 | 更新 `NVCODEC_REF` 或发行版的 oneVPL/AMF/VAAPI 开发库后重建；核对最低驱动要求并在实际设备运行硬件验收 |
| 基础镜像大版本升级（bookworm → trixie） | **必须重建**：glibc/soname 漂移（如 trixie 的 `libssh-5`），这是本方案"构建与运行同发行版"约定的边界 |
| 消费方新增能力需求 | 改 configure + 扩验收门，一次 PR 同时表达"启用"与"验证" |

## 8. 已知取舍与后续演进

当前取舍（接受）：

- **GPLv3**：Linux 的 libsmbclient 要求 `--enable-version3`，两个平台统一使用 GPLv3；
- **发行版锁定**：Linux 产物绑定 bookworm 一代；
- **Windows 无 smb/nfs 协议**：共享文件可经 UNC 访问；RTMP/RTMPS 保留内置实现；
- **AVS 库为小众老库**：davs2/xavs2/uavs3d 上游更新频率低、无发行版安全通道，CVE 响应只能靠手动 bump pin（风险敞口小于主流库，且静态链入无运行时替换歧义）；arm64 上 AVS2 走 C 实现性能有限；AVS3 仅 8bit、仅解码；
- **自动同步会跟随 major 跳跃**：9.x → 10.x 时行为差异（如 9.0 的 tls_verify 类默认值变化）直接进入产物，依赖验收门兜底，重大版本建议先 dispatch 试构建；
- **arm64 依赖托管 runner**：私有仓库场景需 QEMU 或交叉编译兜底；
- **action 未 SHA pin**：v4/v2 tag pin，供应链上是次级风险。

演进方向（按需）：actions SHA pin + OIDC 发布签名；SBOM（syft）；GPU tone-mapping（libplacebo/Vulkan/OpenCL）与更多厂商专用后端；带显卡的自托管 CI；AVS3 10bit 变体（`COMPILE_10BIT=1`）；若消费方需要 DoVi RPU 注入/重标注，引入 dovi_tool（libdovi）作为配套工具。
