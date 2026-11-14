
from PIL import Image
src = r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\xhs_qr_live.png"
dst = r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\xhs_qr_crop.png"
im = Image.open(src)
box = (363, 355, 516, 508)
crop = im.crop(box).resize((612, 612), Image.LANCZOS)
crop.save(dst)
print("ok", crop.size)
