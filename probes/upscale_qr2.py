
from PIL import Image
im = Image.open(r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\xhs_qr_cdp.png")
w,h = im.size
im.resize((w*4,h*4), Image.LANCZOS).save(r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\xhs_qr_cdp_big.png")
print("ok", im.size)
