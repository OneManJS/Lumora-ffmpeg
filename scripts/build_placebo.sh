#!/usr/bin/env bash
# 固定源码并静态链接 libplacebo；Windows 由 FFmpeg 动态加载系统 Vulkan。
build_placebo() {
    local vk_link=enabled
    [[ "$PLATFORM" != win_x64 ]] || vk_link=disabled
    fetch_pinned https://github.com/haasn/libplacebo.git \
        3188549fba13bbdf3a5a98de2a38c2e71f04e21e "$WORKDIR/deps-src/libplacebo"
    git -C "$WORKDIR/deps-src/libplacebo" apply "$ROOT/scripts/patches/libplacebo-python314.patch"
    fetch_pinned https://github.com/KhronosGroup/Vulkan-Headers.git \
        a33416ed2ce6bf8ef48b4eda821825f66d1850d3 "$WORKDIR/deps-src/vulkan-headers"
    cmake -G "Unix Makefiles" -S "$WORKDIR/deps-src/vulkan-headers" -B "$WORKDIR/build-vulkan-headers" \
        -DCMAKE_INSTALL_PREFIX="$DEPS"
    cmake --install "$WORKDIR/build-vulkan-headers"
    fetch_pinned https://github.com/KhronosGroup/SPIRV-Headers.git \
        09913f088a1197aba4aefd300a876b2ebbaa3391 "$WORKDIR/deps-src/spirv-headers"
    cmake -G "Unix Makefiles" -S "$WORKDIR/deps-src/spirv-headers" -B "$WORKDIR/build-spirv-headers" \
        -DCMAKE_INSTALL_PREFIX="$DEPS"
    cmake --install "$WORKDIR/build-spirv-headers"
    if [[ "$PLATFORM" == win_x64 ]]; then
        # 内置头文件模式不会把仅用于探测的 Vulkan loader 写进静态 pc 依赖。
        cp -R "$WORKDIR/deps-src/vulkan-headers/include" \
            "$WORKDIR/deps-src/vulkan-headers/registry" \
            "$WORKDIR/deps-src/libplacebo/3rdparty/Vulkan-Headers/"
    fi
    CFLAGS="-I$DEPS/include" meson setup "$WORKDIR/build-libplacebo" \
        "$WORKDIR/deps-src/libplacebo" --prefix="$DEPS" --libdir=lib \
        --buildtype=release --default-library=static --wrap-mode=nofallback \
        -Dvulkan=enabled -Dvk-proc-addr="$vk_link" -Ddovi=enabled -Dlibdovi=disabled \
        -Dopengl=disabled -Dd3d11=disabled -Dshaderc=disabled -Dglslang=enabled -Dprefer_static=true \
        -Dlcms=disabled -Dunwind=disabled -Dxxhash=disabled -Ddemos=false \
        -Dvulkan-registry="$DEPS/share/vulkan/registry/vk.xml"
    meson compile -C "$WORKDIR/build-libplacebo" -j "$JOBS"
    meson install -C "$WORKDIR/build-libplacebo"
    export PKG_CONFIG_PATH="$DEPS/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
    # glslang/SPIRV 静态库有循环引用，链接器需在组内重复扫描。
    CONFIGURE_FLAGS+=(--extra-cflags="-I$DEPS/include"
        --extra-libs="-Wl,--start-group $(pkg-config --static --libs libplacebo) -Wl,--end-group")
}
