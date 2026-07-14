from PIL import Image, ImageDraw, ImageFont
import os

os.makedirs('chrome_extension/icons', exist_ok=True)

for size in [16, 48, 128]:
    img = Image.new('RGBA', (size, size), (0, 122, 204, 255))
    draw = ImageDraw.Draw(img)
    
    # Рисуем круг
    margin = max(1, size // 16)
    draw.ellipse([margin, margin, size-margin, size-margin], fill=(0, 122, 204, 255))
    
    # Добавляем букву Z (от "Zzz" — сон)
    font_size = int(size * 0.6)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
    
    bbox = draw.textbbox((0, 0), "Z", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (size - tw) // 2
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), "Z", fill=(255, 255, 255, 255), font=font)
    
    img.save(f'chrome_extension/icons/icon{size}.png')

print("✅ Иконки созданы в chrome_extension/icons/")