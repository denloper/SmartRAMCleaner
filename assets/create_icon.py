# create_icon.py - запусти один раз
from PIL import Image, ImageDraw, ImageFont
import os

os.makedirs('assets', exist_ok=True)

sizes = [16, 32, 48, 64, 128, 256]
images = []

for size in sizes:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Градиентный круг
    margin = max(1, size // 16)
    draw.ellipse([margin, margin, size-margin, size-margin], fill=(0, 122, 204, 255))
    
    # Белая обводка
    draw.ellipse([margin, margin, size-margin, size-margin], outline=(255, 255, 255, 220), width=max(1, size//32))
    
    # Буква R
    try:
        font_size = int(size * 0.6)
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), "R", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - bbox[1]
    
    # Тень
    draw.text((x+1, y+1), "R", fill=(0, 0, 0, 180), font=font)
    # Основной текст
    draw.text((x, y), "R", fill=(255, 255, 255, 255), font=font)
    
    images.append(img)

# Сохраняем как ICO со всеми размерами
images[-1].save(
    'assets/icon.ico',
    format='ICO',
    sizes=[(s, s) for s in sizes],
    append_images=images[:-1]
)

print("✅ Иконка создана: assets/icon.ico")