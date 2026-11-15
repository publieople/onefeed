import json, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from onefeed import auth

print("describe:", json.dumps(auth.describe("douyin"), ensure_ascii=False))
t0 = time.time()
info = auth.start("douyin")
print("start %.1fs:" % (time.time() - t0), json.dumps(info, ensure_ascii=False)[:400])

for i in range(4):
    time.sleep(3)
    st = auth.check("douyin")
    print("check:", json.dumps({k: st.get(k) for k in ("state", "cookies", "url", "message")}, ensure_ascii=False))

out = auth.logout("douyin")
print("logout:", json.dumps(out, ensure_ascii=False))
