#!/usr/bin/env bash
# Windows x64 原生构建；必须在 MSYS2 UCRT64 中执行。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM=win_x64
export PYTHONUTF8=1
# shellcheck source=scripts/build_common.sh
source "$ROOT/scripts/build_common.sh"
# shellcheck source=scripts/build_avs_deps.sh
source "$ROOT/scripts/build_avs_deps.sh"
# shellcheck source=scripts/build_hardware.sh
source "$ROOT/scripts/build_hardware.sh"
[[ "${MSYSTEM:-}" == UCRT64 && "$(uname -m)" == x86_64 ]] || fail "需要 MSYS2 UCRT64 x64 环境"
init_build
PYTHON=/ucrt64/bin/python.exe
fetch_ffmpeg
build_avs_deps
build_hardware

cd "$WORKDIR/ffmpeg"
./configure \
    --prefix="$WORKDIR/stage" \
    --disable-autodetect --disable-shared --enable-static \
    --disable-debug --disable-doc --disable-ffplay \
    "${HARDWARE_FLAGS[@]}" --disable-vulkan --disable-opencl \
    --enable-gpl --enable-version3 --enable-libx264 --enable-libx265 --enable-libsvtav1 \
    --enable-libzimg --enable-libdavs2 --enable-libxavs2 --enable-libuavs3d \
    --enable-libdav1d --enable-libbluray --enable-chromaprint --enable-libssh \
    --enable-libass --enable-libfreetype --enable-libfontconfig --enable-libharfbuzz --enable-libfribidi \
    --enable-schannel --enable-zlib --enable-iconv \
    --extra-cflags="-O3 -fstack-protector-strong" \
    --extra-ldflags="-Wl,--dynamicbase,--nxcompat" --extra-libs="-lstdc++"
make -j"$JOBS"
make install
FF="$WORKDIR/stage/bin/ffmpeg.exe"
FP="$WORKDIR/stage/bin/ffprobe.exe"
strip "$FF" "$FP"

echo "==> 收集 DLL 依赖闭包"
"$PYTHON" "$ROOT/scripts/collect_windows_dlls.py" --prefix "$(cygpath -w /ucrt64)" \
    --destination "$(cygpath -w "$WORKDIR/stage/bin")" \
    "$(cygpath -w "$FF")" "$(cygpath -w "$FP")"
# 清除 UCRT64 的 PATH，确保测试真正使用随包 DLL。
ORIGINAL_PATH="$PATH"
PATH="$WORKDIR/stage/bin:/usr/bin:$(cygpath -u "$SYSTEMROOT")/System32"
export PATH
verify_tools
export PATH="$ORIGINAL_PATH"
package_tools
