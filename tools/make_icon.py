"""Genera assets/icon.png y assets/icon.ico (logo simple: disco + S)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([16, 16, S - 16, S - 16], radius=110, fill=(13, 15, 20, 255), outline=(38, 44, 58, 255), width=6)
c = S // 2
for r, col in ((190, (47, 224, 160, 255)), (176, (13, 15, 20, 255)), (150, (30, 35, 48, 255)), (120, (13, 15, 20, 255))):
    d.ellipse([c - r, c - r, c + r, c + r], fill=col)
d.arc([c - 190, c - 190, c + 190, c + 190], start=200, end=300, fill=(255, 79, 139, 255), width=14)
font = None
for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf"):
    try:
        font = ImageFont.truetype(f, 230); break
    except OSError:
        pass
d.text((c, c + 6), "S", font=font, fill=(47, 224, 160, 255), anchor="mm")
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok")
