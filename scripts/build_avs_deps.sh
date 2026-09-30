#!/usr/bin/env bash
# 由平台入口加载；三个 AVS 库均静态链接。

build_avs2_lib() {
    local name="$3"
    local extra=(--enable-pic)
    [[ "$(uname -m)" == x86_64 ]] || extra+=(--disable-asm)
    fetch_pinned "$1" "$2" "$WORKDIR/deps-src/$name"
    echo "==> 构建 $name"
    (cd "$WORKDIR/deps-src/$name/build/linux" && \
        ./configure --prefix="$DEPS" "${extra[@]}" && \
        make -j"$JOBS" && make install)
}

build_avs_deps() {
    build_avs2_lib "${DAVS2_REPO:-https://github.com/pkuvcl/davs2}" \
        "${DAVS2_REF:-b41cf117452e2d73d827f02d3e30aa20f1c721ac}" davs2
    build_avs2_lib "${XAVS2_REPO:-https://github.com/pkuvcl/xavs2}" \
        "${XAVS2_REF:-eae1e8b9d12468059bdd7dee893508e470fa83d8}" xavs2
    fetch_pinned "${UAVS3D_REPO:-https://github.com/uavs3/uavs3d}" \
        "${UAVS3D_REF:-0e20d2c291853f196c68922a264bcd8471d75b68}" "$WORKDIR/deps-src/uavs3d"
    # 上游仍使用较低的 cmake_minimum_required；显式兼容 CMake 4。
    cmake -G "Unix Makefiles" -S "$WORKDIR/deps-src/uavs3d" -B "$WORKDIR/build-uavs3d" \
        -DCMAKE_INSTALL_PREFIX="$DEPS" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCOMPILE_10BIT=OFF -DBUILD_SHARED_LIBS=OFF
    cmake --build "$WORKDIR/build-uavs3d" -j"$JOBS"
    cmake --install "$WORKDIR/build-uavs3d"
    export PKG_CONFIG_PATH="$DEPS/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    pkg-config --exists davs2 xavs2 uavs3d
    test -f "$DEPS/lib/libdavs2.a"
    test -f "$DEPS/lib/libxavs2.a"
    test -f "$DEPS/lib/libuavs3d.a"
}
