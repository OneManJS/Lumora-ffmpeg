#!/usr/bin/env bash
# 将 ref 一次性解析为不可变 commit，三平台共用版本和源码身份。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/build_common.sh
source "$ROOT/scripts/build_common.sh"
ref="${FFMPEG_REF:?需要 FFMPEG_REF}"
validate_ref "$ref"
resolve_dir="$(mktemp -d)"
trap 'rm -rf "$resolve_dir"' EXIT
fetch_pinned "${FFMPEG_REPO:-https://github.com/FFmpeg/FFmpeg.git}" "$ref" "$resolve_dir/source"
commit="$(git -C "$resolve_dir/source" rev-parse HEAD)"
version="$(source_version "$ref" "$commit")"
printf 'ref=%s\ncommit=%s\nversion=%s\n' "$ref" "$commit" "$version" >> "${GITHUB_OUTPUT:-/dev/stdout}"
