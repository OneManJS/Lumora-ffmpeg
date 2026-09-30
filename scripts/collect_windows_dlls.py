#!/usr/bin/env python3
"""通过 PE 导入表收集 UCRT64 DLL 闭包，缺失依赖时立即失败。"""

import argparse
from collections import deque
import os
from pathlib import Path
import re
import shutil
import subprocess


def imports(binary):
    result = subprocess.run(["objdump", "-p", str(binary)], check=True, capture_output=True, text=True)
    return re.findall(r"DLL Name:\s*([^\s]+)", result.stdout, flags=re.IGNORECASE)


def collect(seeds, prefix, destination, system_directory):
    available = {path.name.lower(): path for path in (prefix / "bin").glob("*.dll")}
    system = {path.name.lower() for path in system_directory.glob("*.dll")}
    queue = deque(seeds)
    visited = set()
    dependencies = {}
    while queue:
        binary = queue.popleft()
        key = binary.name.lower()
        if key in visited:
            continue
        visited.add(key)
        for name in imports(binary):
            key = name.lower()
            if key.startswith(("msys-", "cygwin")):
                raise RuntimeError(f"产物意外依赖 MSYS/Cygwin 运行库：{name}")
            if key in available:
                dependencies[key] = available[key]
                queue.append(available[key])
            elif key in system or key.startswith(("api-ms-win-", "ext-ms-win-")):
                continue
            else:
                raise RuntimeError(f"{binary.name} 缺少依赖：{name}")
    destination.mkdir(parents=True, exist_ok=True)
    for dependency in dependencies.values():
        shutil.copy2(dependency, destination / dependency.name)
    return sorted(dependencies)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("binaries", type=Path, nargs="+")
    args = parser.parse_args()
    system_directory = Path(os.environ["SYSTEMROOT"]) / "System32"
    dependencies = collect(args.binaries, args.prefix, args.destination, system_directory)
    print(f"已收集 {len(dependencies)} 个 DLL：{', '.join(dependencies)}")


if __name__ == "__main__":
    main()
