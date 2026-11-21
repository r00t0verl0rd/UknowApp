"""Создаёт значки приложения из действующего логотипа, не меняя иконку iOS."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps

PUBLIC = Path(__file__).resolve().parents[1] / "public"
LOGO = PUBLIC / "logo.png"
BG = "#171b25"
FILES = {
    "favicon-16x16.png": 16,
    "favicon-32x32.png": 32,
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-maskable-512.png": 512,
    "mstile-150x150.png": 150,
}


def load_logo() -> Image.Image:
    """Обрезает прозрачные поля исходного логотипа."""
    with Image.open(LOGO) as source:
        logo = source.convert("RGBA")
    # Убираем только прозрачные края, не изменяя цвета рисунка.
    alpha = logo.getchannel("A").point(lambda value: 255 if value > 8 else 0)
    bounds = alpha.getbbox()
    return logo.crop(bounds) if bounds else logo


def render(logo: Image.Image, size: int, *, background: bool, coverage: float) -> Image.Image:
    """Вписывает логотип по центру квадрата без обрезания."""
    icon = Image.new("RGBA", (size, size), BG if background else (0, 0, 0, 0))
    extent = max(1, round(size * coverage))
    artwork = ImageOps.contain(logo, (extent, extent), Image.Resampling.LANCZOS)
    xy = ((size - artwork.width) // 2, (size - artwork.height) // 2)
    icon.alpha_composite(artwork, xy)
    return icon


def build() -> None:
    """Готовит favicon, иконки Android/Windows и маскируемый значок."""
    logo = load_logo()
    for filename, size in FILES.items():
        maskable = filename == "icon-maskable-512.png"
        small = filename.startswith("favicon-")
        coverage = 0.66 if maskable else (0.96 if small else 0.80)
        icon = render(logo, size, background=not small, coverage=coverage)
        icon.save(PUBLIC / filename, format="PNG", optimize=True)

    # Windows и Firefox читают несколько размеров из одного ICO.
    icon = render(logo, 256, background=False, coverage=0.96)
    icon.save(
        PUBLIC / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    # apple-touch-icon.png остаётся прежним: на iOS он уже отображается верно.


def check() -> None:
    """Проверяет размеры PNG и структуру ICO после сборки."""
    for filename, size in FILES.items():
        with Image.open(PUBLIC / filename) as image:
            if image.format != "PNG" or image.size != (size, size):
                raise ValueError(f"{filename}: ожидается PNG {size}×{size}")

    with Image.open(PUBLIC / "favicon.ico") as icon:
        actual = set(icon.ico.sizes())
        required = {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
        if not required.issubset(actual):
            raise ValueError(f"Не хватает размеров в ICO: {required - actual}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Проверить готовые значки")
    args = parser.parse_args()
    if args.check:
        check()
    else:
        build()
        check()
