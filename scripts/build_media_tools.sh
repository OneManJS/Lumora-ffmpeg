#!/usr/bin/env bash
# Linux 原生构建，动态依赖与运行镜像统一使用 Debian bookworm。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM="${PLATFORM:?需要 PLATFORM 环境变量，如 linux_amd64}"
# shellcheck source=scripts/build_common.sh
source "$ROOT/scripts/build_common.sh"
# shellcheck source=scripts/build_avs_deps.sh
source "$ROOT/scripts/build_avs_deps.sh"

case "$PLATFORM:$(uname -m)" in
    linux_amd64:x86_64|linux_arm64:aarch64) ;;
    *) fail "平台与当前机器架构不匹配：$PLATFORM / $(uname -m)" ;;
esac

echo "==> 安装构建依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends -qq \
    build-essential cmake nasm pkg-config git ca-certificates zip unzip python3 \
    libx264-dev libx265-dev libsvtav1enc-dev libzimg-dev \
    libdav1d-dev libbluray-dev libchromaprint-dev libgnutls28-dev \
    libsmbclient-dev libnfs-dev libssh-dev librtmp-dev zlib1g-dev

init_build
fetch_ffmpeg
build_avs_deps
cd "$WORKDIR/ffmpeg"
./configure \
    --prefix="$WORKDIR/stage" \
    --disable-autodetect --disable-shared --enable-static \
    --disable-debug --disable-doc --disable-ffplay \
    --disable-hwaccels --disable-vaapi --disable-vdpau --disable-libdrm \
    --disable-vulkan --disable-opencl --disable-ffnvcodec \
    --enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libsvtav1 \
    --enable-libzimg --enable-libdavs2 --enable-libxavs2 --enable-libuavs3d \
    --enable-libdav1d --enable-libbluray --enable-chromaprint \
    --enable-libsmbclient --enable-libnfs --enable-libssh --enable-librtmp \
    --enable-gnutls --enable-zlib --enable-iconv \
    --extra-cflags="-O3 -fstack-protector-strong -D_FORTIFY_SOURCE=2" \
    --extra-ldflags="-Wl,-z,relro,-z,now" --extra-libs="-lstdc++"
make -j"$JOBS"
make install
FF="$WORKDIR/stage/bin/ffmpeg"
FP="$WORKDIR/stage/bin/ffprobe"
strip "$FF" "$FP"
verify_tools
package_tools
