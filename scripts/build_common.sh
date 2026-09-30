#!/usr/bin/env bash
# 两个平台共用的构建环境、源码获取和审计记录。

fail() { echo "错误：$*" >&2; exit 1; }

validate_ref() {
    [[ "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9._/-]*$ ]] || fail "无效的源码 ref：$1"
    git check-ref-format --branch "$1" >/dev/null || fail "无效的源码 ref：$1"
}

fetch_pinned() {
    local repo="$1" ref="$2" dest="$3" attempt
    validate_ref "$ref"
    git init -q "$dest"
    git -C "$dest" remote add origin "$repo"
    for attempt in 1 2 3; do
        if git -C "$dest" fetch -q --depth 1 origin "$ref"; then
            git -C "$dest" checkout -q --detach FETCH_HEAD
            return
        fi
        echo "源码获取失败（第 $attempt 次）：$repo @ $ref" >&2
    done
    fail "无法获取源码：$repo @ $ref"
}

source_version() {
    if [[ "$1" =~ ^n[0-9]+\.[0-9]+(\.[0-9]+)*$ ]]; then
        printf '%s\n' "${1#n}"
    else
        printf 'g%.12s\n' "$2"
    fi
}

init_build() {
    FFMPEG_REF="${FFMPEG_REF:-n9.0.2}"
    validate_ref "$FFMPEG_REF"
    JOBS="${JOBS:-$(nproc)}"
    [[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || fail "JOBS 必须是正整数"
    local base="${WORKDIR:-$ROOT/.tmp-media-tools-build}"
    DIST="${DIST:-$ROOT/dist}"
    mkdir -p "$base" "$DIST"
    base="$(cd "$base" && pwd)"
    DIST="$(cd "$DIST" && pwd)"
    # 每次使用独立目录，避免旧对象、DLL 和 CMake 缓存混入新产物。
    WORKDIR="$(mktemp -d "$base/${PLATFORM}.XXXXXX")"
    DEPS="$WORKDIR/deps"
    export WORKDIR DIST PLATFORM DEPS
    echo "==> 构建目录：$WORKDIR"
    trap archive_build_logs EXIT
}

archive_build_logs() {
    local status=$? file
    trap - EXIT
    mkdir -p "$DIST/logs.$PLATFORM"
    for file in "$WORKDIR/ffmpeg/ffbuild/config.log" \
        "$WORKDIR/build-libplacebo/meson-logs/meson-log.txt" \
        "$WORKDIR/deps-src/davs2/build/linux/config.log" \
        "$WORKDIR/deps-src/xavs2/build/linux/config.log"; do
        if [[ -f "$file" ]]; then
            local relative="${file#"$WORKDIR/"}"
            cp "$file" "$DIST/logs.$PLATFORM/${relative//\//_}" || true
        fi
    done
    if (( status != 0 )); then
        echo "构建失败，工作目录保留在 $WORKDIR，诊断日志位于 $DIST/logs.$PLATFORM" >&2
    fi
    exit "$status"
}

fetch_ffmpeg() {
    fetch_pinned "${FFMPEG_REPO:-https://github.com/FFmpeg/FFmpeg.git}" \
        "${FFMPEG_COMMIT:-$FFMPEG_REF}" "$WORKDIR/ffmpeg"
    FFMPEG_SHA="$(git -C "$WORKDIR/ffmpeg" rev-parse HEAD)"
    if [[ -n "${FFMPEG_COMMIT:-}" && "$FFMPEG_SHA" != "$FFMPEG_COMMIT" ]]; then
        fail "FFmpeg commit 与解析结果不一致"
    fi
    VERSION="$(source_version "$FFMPEG_REF" "$FFMPEG_SHA")"
    if [[ -n "${FFMPEG_VERSION:-}" && "$VERSION" != "$FFMPEG_VERSION" ]]; then
        fail "FFmpeg 产物版本与解析结果不一致"
    fi
    export VERSION
    echo "==> FFmpeg $VERSION（$PLATFORM，$FFMPEG_SHA）"
}

write_build_info() {
    local name
    {
        printf 'platform=%s\nversion=%s\nffmpeg_ref=%s\nffmpeg_commit=%s\n' \
            "$PLATFORM" "$VERSION" "$FFMPEG_REF" "$FFMPEG_SHA"
        printf 'build_scripts_commit=%s\n' "${GITHUB_SHA:-unknown}"
        printf '\n源码补丁 SHA256：\n'
        (cd "$ROOT" && sha256sum scripts/patches/*.patch)
        for name in davs2 xavs2 uavs3d nv-codec-headers libplacebo vulkan-headers spirv-headers; do
            [[ -d "$WORKDIR/deps-src/$name" ]] || continue
            printf '%s_commit=%s\n' "$name" "$(git -C "$WORKDIR/deps-src/$name" rev-parse HEAD)"
            printf '%s_repo=%s\n' "$name" "$(git -C "$WORKDIR/deps-src/$name" remote get-url origin)"
        done
        printf 'ffmpeg_repo=%s\n' "$(git -C "$WORKDIR/ffmpeg" remote get-url origin)"
        printf '\n编译器：\n'
        cc --version
        printf '\n运行依赖：\n'
        ldd "$FF"
        ldd "$FP"
        printf '\n构建环境软件包：\n'
        if [[ "$PLATFORM" == win_x64 ]]; then pacman -Q; else dpkg-query -W; fi
    } > "$DIST/build-info.$PLATFORM.txt"
    cp "$WORKDIR/ffmpeg/ffbuild/config.log" "$DIST/config.$PLATFORM.log"
}

verify_tools() {
    local options=()
    # 按源码能力选择验收项，兼容 8.x 和非稳定分支版本字符串。
    if [[ ! -f "$WORKDIR/ffmpeg/libavcodec/bsf/dovi_split.c" ]]; then
        options+=(--allow-missing-dovi-split)
    fi
    "${PYTHON:-python3}" "$ROOT/scripts/verify_media_tools.py" --ffmpeg "$FF" --ffprobe "$FP" \
        --platform "$PLATFORM" "${options[@]}"
}

package_tools() {
    local suffix="" tool archive
    local extra=()
    if [[ "$PLATFORM" == win_x64 ]]; then
        suffix=".exe"
        extra=("$WORKDIR/stage/bin/"*.dll)
    fi
    write_build_info
    for tool in ffmpeg ffprobe; do
        archive="$DIST/${tool}_${VERSION}_${PLATFORM}.zip"
        # zip 默认更新旧包，必须先移除同名包以免保留历史文件。
        rm -f "$archive"
        zip -q -j "$archive" "$WORKDIR/stage/bin/$tool$suffix" "${extra[@]}"
        unzip -tq "$archive"
    done
    (cd "$DIST" && sha256sum "ffmpeg_${VERSION}_${PLATFORM}.zip" \
        "ffprobe_${VERSION}_${PLATFORM}.zip" "config.$PLATFORM.log" \
        "build-info.$PLATFORM.txt" > "SHA256SUMS.$PLATFORM.txt")
    echo "==> 构建完成：$DIST"
}
