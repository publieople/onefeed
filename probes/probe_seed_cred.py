import os, shutil, traceback
from pathlib import Path
src = Path(os.environ["APPDATA"]) / "bili-cli" / "credential.json"
print("src:", src, "exists:", src.exists())
try:
    data = src.read_text(encoding="utf-8")
    print("read OK, chars:", len(data))
except Exception as e:
    print("read FAIL:", type(e).__name__, e)
dst_dir = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\.onefeed\toolhome\bili-cli")
dst_dir.mkdir(parents=True, exist_ok=True)
dst = dst_dir / "credential.json"
try:
    shutil.copyfile(src, dst)
    print("copy OK ->", dst, dst.stat().st_size)
except Exception as e:
    print("copy FAIL:", type(e).__name__, e)
