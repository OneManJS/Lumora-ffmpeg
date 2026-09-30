#!/usr/bin/env python3
"""在独立前缀修正 MSYS2 静态链接元数据，不修改系统软件包。"""

import argparse
from pathlib import Path


def static_pc(contents, name):
    lines = []
    additions = {"Requires.private": "libcrypto zlib", "Libs.private": "-liphlpapi"} if name == "libssh" else {}
    for line in contents.splitlines():
        field, separator, value = line.partition(":")
        if name == "x265" and field == "Libs.private":
            # GCC 自行加入静态运行库，包中的 -lgcc_s 实际指向 DLL 导入库。
            value = " " + " ".join(flag for flag in value.split() if flag not in {"-lgcc_s", "-lgcc"})
        if field in additions:
            # MSYS2 的 libssh.pc 未完整声明静态库依赖。
            value = " " + " ".join(filter(None, (value.strip(), additions.pop(field))))
        lines.append(field + separator + value)
    lines.extend(f"{field}: {value}" for field, value in additions.items())
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for name in ("x265", "libssh"):
        source = args.prefix / "lib/pkgconfig" / f"{name}.pc"
        contents = source.read_text(encoding="utf-8")
        # 移动 pc 文件后必须保留原软件包前缀，而不是让 pkgconf 根据新路径重定位。
        contents = "\n".join(f"package_prefix={args.prefix.as_posix()}" if line.startswith("prefix=")
                             else line for line in contents.splitlines())
        contents = contents.replace("${prefix}", "${package_prefix}")
        (args.destination / source.name).write_text(static_pc(contents, name), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
