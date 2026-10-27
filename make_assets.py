"""Make the game pictures. Run this on your computer:  python make_assets.py

It copies every picture in raw_art/ into assets/ three times bigger, using nearest
neighbour so the pixels stay crisp instead of blurring. It also makes two coloured
crystal gems from raw_art/gem.png. main.py only reads the finished files in assets/.
"""

import os

from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_FOLDER = os.path.join(ROOT, "raw_art")
ASSET_FOLDER = os.path.join(ROOT, "assets")

SCALE = 3

# dark and light end of each gem, from the shading of gem.png
GEMS = {
    "gem_blue.png": ((8, 24, 96), (110, 214, 255)),
    "gem_pink.png": ((74, 8, 96), (255, 132, 226)),
}


def grow(image):
    return image.resize((image.width * SCALE, image.height * SCALE), Image.NEAREST)


def tint(image, dark, light):
    """Keep the shading and the shape, but change the colour."""
    coloured = ImageOps.colorize(image.convert("L"), black=dark, white=light).convert("RGBA")
    coloured.putalpha(image.getchannel("A"))
    return coloured


def build():
    os.makedirs(ASSET_FOLDER, exist_ok=True)
    made = []
    for name in sorted(os.listdir(RAW_FOLDER)):
        if not name.lower().endswith(".png"):
            continue
        with Image.open(os.path.join(RAW_FOLDER, name)) as handle:
            grow(handle.convert("RGBA")).save(os.path.join(ASSET_FOLDER, name))
        made.append(name)

    with Image.open(os.path.join(RAW_FOLDER, "gem.png")) as handle:
        gem = handle.convert("RGBA")
        for name, (dark, light) in GEMS.items():
            grow(tint(gem, dark, light)).save(os.path.join(ASSET_FOLDER, name))
            made.append(name)
    return made


if __name__ == "__main__":
    for file_name in build():
        print("assets/" + file_name)
    print(f"{len(os.listdir(ASSET_FOLDER))} files in assets/, made {SCALE}x bigger than raw_art/")
