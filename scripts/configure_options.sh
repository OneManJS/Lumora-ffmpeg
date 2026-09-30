#!/usr/bin/env bash
# 预检与正式配置共用同一组参数，避免两份配置漂移。

set_configure_options() {
    set_hardware_flags
    CONFIGURE_FLAGS=(
        --prefix="$WORKDIR/stage"
        --disable-autodetect --disable-shared --enable-static
        --disable-debug --disable-doc --disable-ffplay
        "${HARDWARE_FLAGS[@]}" --enable-vulkan --enable-libplacebo --disable-opencl
        --enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libsvtav1
        --enable-libzimg --enable-libdavs2 --enable-libxavs2 --enable-libuavs3d
        --enable-libdav1d --enable-libbluray --enable-chromaprint --enable-libssh
        --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz --enable-libfribidi
        --enable-zlib --enable-iconv --extra-libs=-lstdc++
    )
    if [[ "$PLATFORM" == win_x64 ]]; then
        # 关闭自动探测后 FFmpeg 仅尝试 libc iconv，UCRT 需显式链接独立库。
        CONFIGURE_FLAGS+=(--enable-schannel
            --extra-libs=-liconv
            --extra-cflags="-O3 -fstack-protector-strong"
            --extra-ldflags="-Wl,--dynamicbase,--nxcompat")
    else
        CONFIGURE_FLAGS+=(--enable-libsmbclient --enable-librtmp --enable-gnutls
            --extra-cflags="-O3 -fstack-protector-strong -D_FORTIFY_SOURCE=2"
            --extra-ldflags="-Wl,-z,relro,-z,now")
    fi
}

check_configure_options() {
    local log="$DIST/logs.$PLATFORM/configure-options.log"
    mkdir -p "$(dirname "$log")"
    echo "==> 预检 FFmpeg configure 参数（$PLATFORM）"
    # --help 必须放在最后：上游逐项解析参数，发现未知选项时先失败，
    # 合法参数则在编译器和依赖探测前退出；这不代替正式 configure。
    if ! (cd "$WORKDIR/ffmpeg" && ./configure "${CONFIGURE_FLAGS[@]}" --help) > "$log" 2>&1; then
        cat "$log" >&2
        return 1
    fi
}
