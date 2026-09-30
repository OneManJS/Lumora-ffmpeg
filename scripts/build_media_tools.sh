#!/usr/bin/env bash
# Linux 原生构建，动态依赖与运行镜像统一使用 Debian bookworm。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM="${PLATFORM:?需要 PLATFORM 环境变量，如 linux_amd64}"
# shellcheck source=scripts/build_common.sh
source "$ROOT/scripts/build_common.sh"
# shellcheck source=scripts/build_avs_deps.sh
source "$ROOT/scripts/build_avs_deps.sh"
# shellcheck source=scripts/build_hardware.sh
source "$ROOT/scripts/build_hardware.sh"
# shellcheck source=scripts/configure_options.sh
source "$ROOT/scripts/configure_options.sh"
# shellcheck source=scripts/build_placebo.sh
source "$ROOT/scripts/build_placebo.sh"

case "$PLATFORM:$(uname -m)" in
    linux_amd64:x86_64|linux_arm64:aarch64) ;;
    *) fail "平台与当前机器架构不匹配：$PLATFORM / $(uname -m)" ;;
esac
platform_packages=()
if [[ "$PLATFORM" == linux_amd64 ]]; then platform_packages+=(libvpl-dev); fi

echo "==> 安装构建依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends -qq \
    build-essential cmake clang nasm pkg-config git ca-certificates zip unzip python3 \
    libx264-dev libx265-dev libsvtav1enc-dev libzimg-dev \
    libdav1d-dev libbluray-dev libchromaprint-dev libgnutls28-dev \
    libsmbclient-dev libssh-dev librtmp-dev zlib1g-dev \
    libva-dev libvdpau-dev libdrm-dev \
    libvulkan-dev spirv-tools glslang-dev \
    meson ninja-build python3-jinja2 libfast-float-dev \
    libass-dev libfreetype-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev \
    fonts-dejavu-core "${platform_packages[@]}"

init_build
fetch_ffmpeg
set_configure_options
check_configure_options
build_avs_deps
build_hardware
build_placebo
cd "$WORKDIR/ffmpeg"
./configure "${CONFIGURE_FLAGS[@]}"
make -j"$JOBS"
make install
FF="$WORKDIR/stage/bin/ffmpeg"
FP="$WORKDIR/stage/bin/ffprobe"
strip "$FF" "$FP"
verify_tools
package_tools
