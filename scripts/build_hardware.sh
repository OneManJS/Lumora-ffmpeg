#!/usr/bin/env bash
# 显式启用平台支持的 GPU 后端；构建阶段只需开发头文件，不要求安装显卡驱动。

build_hardware() {
    fetch_pinned "${NVCODEC_REPO:-https://github.com/FFmpeg/nv-codec-headers.git}" \
        "${NVCODEC_REF:-n12.1.14.0}" "$WORKDIR/deps-src/nv-codec-headers"
    make -C "$WORKDIR/deps-src/nv-codec-headers" PREFIX="$DEPS" install
    export PKG_CONFIG_PATH="$DEPS/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    pkg-config --exists ffnvcodec

    HARDWARE_FLAGS=(--enable-ffnvcodec --enable-nvenc --enable-nvdec --enable-cuvid --enable-cuda-llvm)
    case "$PLATFORM" in
        linux_amd64)
            HARDWARE_FLAGS+=(--enable-vaapi --enable-vdpau --enable-libdrm --enable-v4l2-m2m --enable-libvpl)
            ;;
        linux_arm64)
            HARDWARE_FLAGS+=(--enable-vaapi --enable-vdpau --enable-libdrm --enable-v4l2-m2m)
            ;;
        win_x64)
            HARDWARE_FLAGS+=(--enable-libvpl --enable-amf --enable-dxva2 --enable-d3d11va --enable-d3d12va)
            ;;
        *) fail "不支持的硬件构建平台：$PLATFORM" ;;
    esac
}
