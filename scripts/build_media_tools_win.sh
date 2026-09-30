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
[[ "${MSYSTEM:-}" == UCRT64 && "$(uname -m)" == x86_64 ]] || fail "需要 MSYS2 UCRT64 x64 环境"
init_build
PYTHON=/ucrt64/bin/python.exe
fetch_ffmpeg
set_configure_options
check_configure_options
build_avs_deps
build_hardware

cd "$WORKDIR/ffmpeg"
./configure "${CONFIGURE_FLAGS[@]}"
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
