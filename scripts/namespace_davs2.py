#!/usr/bin/env python3
"""隔离 davs2 静态库的全局符号，防止两种位深的函数和全局状态串用。"""

import argparse
from pathlib import Path
import subprocess
import tempfile


def namespace(source, destination, prefix, *, nm="nm", objcopy="objcopy"):
    result = subprocess.run([nm, "-g", "--defined-only", str(source)],
                            check=True, capture_output=True, text=True)
    symbols = {parts[2] for line in result.stdout.splitlines()
               if len(parts := line.split()) == 3 and len(parts[1]) == 1}
    if "davs2_decoder_open" not in symbols:
        raise RuntimeError("静态库中缺少 davs2 公共接口")
    # Windows 的引用指针位于 COMDAT 节；同时改节名，避免链接器合并不同后端的指针。
    sections = []
    mapping_lines = [f"{name} {prefix}{name}\n" for name in sorted(symbols)]
    for symbol in sorted(symbols):
        if symbol.startswith(".refptr."):
            sections.extend(["--rename-section",
                             f".rdata${symbol}=.rdata${prefix}{symbol}"])
            mapping_lines.append(f".rdata${symbol} .rdata${prefix}{symbol}\n")
    with tempfile.TemporaryDirectory(prefix="davs2-symbols-") as directory:
        mapping = Path(directory) / "symbols.txt"
        mapping.write_text("".join(mapping_lines), encoding="ascii")
        subprocess.run([objcopy, f"--redefine-syms={mapping}", *sections,
                        str(source), str(destination)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("prefix", choices=("lumora8_", "lumora10_"))
    parser.add_argument("--nm", default="nm")
    parser.add_argument("--objcopy", default="objcopy")
    args = parser.parse_args()
    namespace(args.source, args.destination, args.prefix, nm=args.nm, objcopy=args.objcopy)


if __name__ == "__main__":
    main()
