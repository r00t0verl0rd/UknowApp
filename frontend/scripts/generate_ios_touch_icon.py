"""Generate the single iOS PNG compatibility asset from logo-main.svg.

SVG markers used by the logo must be rendered by Inkscape (CairoSVG drops them).
This is not a second logo source; it only exports the same art for iOS Home Screen.
"""

from pathlib import Path
from subprocess import run
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

PUBLIC = Path(__file__).resolve().parents[1] / "public"
SOURCE = PUBLIC / "logo-main.svg"
TARGET = PUBLIC / "apple-touch-icon.png"
COLOR = "#202938"
RENDER_SIZE = 360
ART_SIZE = 288
OUTPUT_SIZE = 180


def main() -> None:
    with TemporaryDirectory() as directory:
        temp_png = Path(directory) / "uknow.png"
        run([
            "inkscape", str(SOURCE), "--export-type=png",
            f"--export-filename={temp_png}",
            f"--export-width={RENDER_SIZE}",
            f"--export-height={RENDER_SIZE}",
        ], check=True)
        with Image.open(temp_png) as rendered:
            artwork = ImageOps.contain(rendered.convert("RGBA"), (ART_SIZE, ART_SIZE))
        background = Image.new("RGBA", (RENDER_SIZE, RENDER_SIZE), COLOR)
        background.alpha_composite(
            artwork, ((RENDER_SIZE - artwork.width) // 2, (RENDER_SIZE - artwork.height) // 2),
        )
        # A 180x180 RGB PNG is guaranteed to work for the iOS Home Screen.
        icon = background.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.Resampling.LANCZOS)
        icon.convert("RGB").save(TARGET, "PNG", optimize=True)


if __name__ == "__main__":
    main()
