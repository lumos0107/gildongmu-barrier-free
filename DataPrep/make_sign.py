"""Unity 장면의 '가상 세계' 표지 그림(한글은 Unity 기본 글꼴에 없어 그림으로 만든다).
사용: python -I make_sign.py --out ../Assets/Gildongmu/Minsokchon/Data/virtual_sign.png"""
import argparse

from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 384
BLUE = (26, 90, 204)


def make(path: str) -> None:
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, W - 11, H - 11], outline=BLUE, width=14)
    big = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 150)
    small = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 46)
    d.text((W / 2, 135), "가상 세계", font=big, fill=BLUE, anchor="mm")
    d.text((W / 2, 262), "가상 값으로 만든 시험용 3D 맵", font=small, fill=(40, 40, 40), anchor="mm")
    d.text((W / 2, 318), "실제 측정값이 아님", font=small, fill=(200, 60, 30), anchor="mm")
    im.save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    make(ap.parse_args().out)
