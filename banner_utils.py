import os
import random
import re
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BANNERS_DIR = os.path.join(BASE_DIR, "assets", "banners")
OUTPUT_DIR = os.path.join(BASE_DIR, "generated_banners")
os.makedirs(BANNERS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_а-яА-Я-]", "_", value)[:40]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def ensure_default_banners() -> None:
    existing = [f for f in os.listdir(BANNERS_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
    if existing:
        return

    themes = [
        ((34, 44, 84), (88, 101, 242), (241, 196, 15)),
        ((28, 22, 58), (155, 89, 182), (88, 101, 242)),
        ((38, 31, 20), (241, 196, 15), (231, 76, 60)),
        ((18, 40, 38), (46, 204, 113), (52, 152, 219)),
    ]
    for index, (base, a, b) in enumerate(themes, start=1):
        img = Image.new("RGBA", (1000, 300), base + (255,))
        draw = ImageDraw.Draw(img)
        for x in range(1000):
            mix = x / 999
            color = tuple(int(a[i] * mix + base[i] * (1 - mix)) for i in range(3))
            draw.line([(x, 0), (x, 300)], fill=color + (255,))
        for _ in range(28):
            x = random.randint(0, 1000)
            y = random.randint(0, 300)
            r = random.randint(12, 60)
            draw.ellipse((x - r, y - r, x + r, y + r), outline=b + (70,), width=3)
        img = img.filter(ImageFilter.GaussianBlur(0.4))
        img.save(os.path.join(BANNERS_DIR, f"ranko_bg_{index}.png"))


async def generate_level_banner(member, level: int) -> Optional[str]:
    ensure_default_banners()
    backgrounds = [
        os.path.join(BANNERS_DIR, f)
        for f in os.listdir(BANNERS_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ]
    if not backgrounds:
        return None

    bg_path = random.choice(backgrounds)
    background = Image.open(bg_path).convert("RGBA").resize((1000, 300))
    overlay = Image.new("RGBA", background.size, (0, 0, 0, 90))
    background = Image.alpha_composite(background, overlay)
    draw = ImageDraw.Draw(background)

    avatar_bytes = await member.display_avatar.replace(size=256, static_format="png").read()
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))
    mask = Image.new("L", (150, 150), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, 150, 150), fill=255)

    draw.rounded_rectangle((32, 38, 968, 262), radius=32, fill=(12, 14, 22, 145), outline=(255, 255, 255, 38), width=2)
    draw.ellipse((55, 75, 205, 225), fill=(255, 255, 255, 255))
    background.paste(avatar, (55, 75), mask)

    big = _font(52, bold=True)
    mid = _font(31, bold=True)
    small = _font(24, bold=False)
    tiny = _font(18, bold=False)

    draw.text((235, 73), str(member.display_name), font=big, fill=(255, 255, 255))
    draw.text((238, 138), f"достиг milestone-уровня {level}", font=mid, fill=(255, 224, 95))
    draw.text((238, 185), "Ranko поздравляет с новой планкой активности", font=small, fill=(220, 225, 240))
    draw.text((800, 218), "RANKO LEVEL UP", font=tiny, fill=(180, 190, 220))

    output = os.path.join(OUTPUT_DIR, f"ranko_banner_{_safe_name(member.name)}_{member.id}_{level}.png")
    background.save(output)
    return output
