import os, sys, tempfile, traceback
from pathlib import Path
print("exe:", sys.executable)
print("ver:", sys.version.replace("\n", " "))
print("prefix:", sys.prefix)
seen = Path(os.environ["APPDATA"]) / "bili-cli" / "seen.json"
print("seen:", seen, "exists:", seen.exists())
for label, target in [("appdata/bili-cli/seen.json", seen),
                      ("appdata/tmp_probe.txt", Path(os.environ["APPDATA"]) / "dsh_write_probe.txt"),
                      ("workspace/tmp_probe.txt", Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\tmp") / "dsh_write_probe.txt"),
                      ("tempdir/tmp_probe.txt", Path(tempfile.gettempdir()) / "dsh_write_probe.txt")]:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("probe", encoding="utf-8")
        print(f"write {label}: OK")
    except Exception as e:
        print(f"write {label}: FAIL {type(e).__name__}: {e}")

# 看进程令牌里有没有受限 SID / AppContainer
import ctypes
from ctypes import wintypes
adv = ctypes.windll.advapi32
k32 = ctypes.windll.kernel32
tok = wintypes.HANDLE()
if adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):
    appc = ctypes.c_void_p()
    size = wintypes.DWORD(0)
    r = adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(size))  # TokenIsAppContainer
    print("TokenIsAppContainer query size:", size.value)
