
import os, sys, time
os.environ.setdefault("PYTHONUTF8","1")
os.environ.setdefault("PYTHONIOENCODING","utf-8")
os.environ["HTTP_PROXY"]="http://127.0.0.1:7890"
os.environ["HTTPS_PROXY"]="http://127.0.0.1:7890"
import camoufox.pkgman as pm
print("INSTALL_DIR", pm.INSTALL_DIR, flush=True)
try:
    pm.CamoufoxFetcher().install()
    print("INSTALL_OK", flush=True)
except Exception as exc:
    print("INSTALL_FAIL", type(exc).__name__, str(exc)[:400], flush=True)
