
import json, os, shutil, sqlite3, sys
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
home = ROOT / ".onefeed" / "tmp" / "probehome"
home.mkdir(parents=True, exist_ok=True)
src = ROOT / ".onefeed" / "onefeed.db"
dst = home / "onefeed.db"
if dst.exists(): dst.unlink()
shutil.copy2(src, dst)
con = sqlite3.connect(dst)
rows = con.execute("select id, cover, images from items where platform='xiaohongshu' and kind='images' limit 6").fetchall()
for rid, cover, images in rows:
    try: imgs = json.loads(images or "[]")
    except Exception: imgs = []
    if cover and cover not in imgs: imgs = [cover] + imgs
    print(rid, len(imgs))
base = rows[0][1]
patch = [base, base.replace("!nc_n_webp_mw_1", "!nc_n_webp_mw_2"), base]
con.execute("update items set images=? where id=?", (json.dumps(patch), rows[0][0]))
con.commit()
print("patched:", rows[0][0], "->", len(patch), "images")
con.close()
