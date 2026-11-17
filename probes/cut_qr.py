from PIL import Image
src = r"E:\Documents\deepseek-harness\default-workspace\onefeed\design\zhihu-login-live.png"
im = Image.open(src)
# generous window around the QR found at roughly (390,487)-(555,652)
crop = im.crop((372, 470, 578, 676))
crop = crop.resize((crop.width*4, crop.height*4), Image.LANCZOS)
crop.save(r"E:\Documents\deepseek-harness\default-workspace\onefeed\design\zhihu-qr-cut2.png")
print("saved", crop.size)
