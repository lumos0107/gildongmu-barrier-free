"""제주대 Unity 장면의 '가상 값 섞임' 표지 그림(한글은 Unity 기본 글꼴에 없어 그림으로 만든다).
민속촌 DataPrep/make_sign.py와 같은 크기(1024x384, JejunuMaker가 이 비율로 판을 만든다)에 문구만 다르다.
사용: python -I DataPrep/jejunu/make_sign.py --out Assets/Gildongmu/Jejunu1000/Data/virtual_sign.png"""
import argparse

from PIL import Image, ImageDraw, ImageFont

W, H = 1024, 384
BLUE = (26, 90, 204)
LINES = ("공개 지도 + 가상 값으로 만든 3D 맵", "턱 높이·좌우 기울기 등은 가상", "실제 측정값 아님")


def make(path: str) -> None:
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([10, 10, W - 11, H - 11], outline=BLUE, width=14)
    big = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 54)
    mid = ImageFont.truetype(r"C:\Windows\Fonts\malgun.ttf", 50)
    red = ImageFont.truetype(r"C:\Windows\Fonts\malgunbd.ttf", 60)
    d.text((W / 2, 105), LINES[0], font=big, fill=BLUE, anchor="mm")
    d.text((W / 2, 200), LINES[1], font=mid, fill=(40, 40, 40), anchor="mm")
    d.text((W / 2, 292), LINES[2], font=red, fill=(200, 60, 30), anchor="mm")
    im.save(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    make(ap.parse_args().out)
