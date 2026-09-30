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
# shellcheck source=scripts/configure_options.sh
source "$ROOT/scripts/configure_options.sh"
# shellcheck source=scripts/build_placebo.sh
source "$ROOT/scripts/build_placebo.sh"
[[ "${MSYSTEM:-}" == UCRT64 && "$(uname -m)" == x86_64 ]] || fail "需要 MSYS2 UCRT64 x64 环境"
init_build
PYTHON=/ucrt64/bin/python.exe
fetch_ffmpeg
set_configure_options
check_configure_options
build_avs_deps
build_hardware
build_placebo
"$PYTHON" "$ROOT/scripts/prepare_windows_static.py" --prefix "$(cygpath -m /ucrt64)" \
    --destination "$(cygpath -m "$DEPS/lib/pkgconfig")"
# FreeType 与 HarfBuzz 相互引用，静态链接需要在组内重复扫描。
CONFIGURE_FLAGS+=(--extra-libs="-Wl,--start-group $(pkg-config --static --libs harfbuzz freetype2) -Wl,--end-group")

cd "$WORKDIR/ffmpeg"
./configure "${CONFIGURE_FLAGS[@]}"
make -j"$JOBS"
make install
FF="$WORKDIR/stage/bin/ffmpeg.exe"
FP="$WORKDIR/stage/bin/ffprobe.exe"
strip "$FF" "$FP"

echo "==> 验证单文件 EXE 的系统 DLL 依赖"
"$PYTHON" "$ROOT/scripts/verify_windows_static.py" \
    "$(cygpath -w "$FF")" "$(cygpath -w "$FP")"
# 清除 UCRT64 的 PATH，确保测试不依赖工具链 DLL。
ORIGINAL_PATH="$PATH"
PATH="$WORKDIR/stage/bin:/usr/bin:$(cygpath -u "$SYSTEMROOT")/System32"
export PATH
verify_tools
export PATH="$ORIGINAL_PATH"
package_tools
