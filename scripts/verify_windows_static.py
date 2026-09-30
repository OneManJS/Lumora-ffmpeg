#!/usr/bin/env python3
"""单文件发行门禁：只允许 Windows 系统 PE 导入，不从工具链目录补 DLL。"""

import argparse
from pathlib import Path

from collect_windows_dlls import imports


# 显式允许系统组件，不能因为某个第三方 DLL 恰好存在于 System32 就放行。
SYSTEM_DLLS = set("""
advapi32.dll avicap32.dll avrt.dll bcrypt.dll cabinet.dll cfgmgr32.dll combase.dll comctl32.dll
comdlg32.dll crypt32.dll d3d11.dll d3d12.dll d3d9.dll dbghelp.dll dnsapi.dll dwmapi.dll dwrite.dll
dxgi.dll dxva2.dll gdi32.dll imm32.dll iphlpapi.dll kernel32.dll kernelbase.dll
mf.dll mfplat.dll mfuuid.dll mfreadwrite.dll msacm32.dll msvcrt.dll ncrypt.dll
netapi32.dll normaliz.dll ntdll.dll ole32.dll oleaut32.dll powrprof.dll propsys.dll
psapi.dll rpcrt4.dll secur32.dll setupapi.dll shell32.dll shlwapi.dll strmiids.dll
ucrtbase.dll user32.dll userenv.dll usp10.dll uuid.dll version.dll vfw32.dll
winhttp.dll wininet.dll winmm.dll winspool.drv ws2_32.dll wtsapi32.dll
""".split())


def verify(binary):
    names = imports(binary)
    unexpected = sorted(name for name in names if name.lower() not in SYSTEM_DLLS
                        and not name.lower().startswith(("api-ms-win-", "ext-ms-win-")))
    if unexpected:
        raise RuntimeError(f"{binary.name} 仍依赖非系统 DLL：{', '.join(unexpected)}")
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binaries", type=Path, nargs="+")
    args = parser.parse_args()
    for binary in args.binaries:
        print(f"{binary.name} 系统依赖：{', '.join(verify(binary))}")


if __name__ == "__main__":
    main()
