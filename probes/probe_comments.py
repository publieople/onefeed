
import sys, os
sys.path.insert(0, r"E:\Documents\deepseek-harness\default-workspace")
from onefeed.adapters import make
a = make("douyin", log=lambda m: print(m, file=sys.stderr))
a.start()
items = a.pull(limit=2)
print("ITEMS", len(items), file=sys.stderr)
if items:
    cs = a.comments(items[0], limit=8)
    print("COMMENTS", len(cs))
    for c in cs[:5]:
        print(f"  ♥{c.like:>4} {c.author}: {c.text[:50]}")
a.close()
