"""Generate a standards-size PWA PNG from the user-supplied 512px logo."""

from pathlib import Path

from PIL import Image

PUBLIC = Path(__file__).resolve().parents[1] / "public"
SOURCE = PUBLIC / "logo-big.png"
DESTINATION = PUBLIC / "logo-192.png"


def main() -> None:
    with Image.open(SOURCE) as source:
        if source.size != (512, 512) or source.format != "PNG":
            raise ValueError("logo-big.png must be a 512×512 PNG")
        artwork = source.convert("RGBA")
    artwork.resize((192, 192), Image.Resampling.LANCZOS).save(
        DESTINATION, format="PNG", optimize=True,
    )
    with Image.open(DESTINATION) as icon:
        if icon.format != "PNG" or icon.size != (192, 192):
            raise ValueError("Failed to generate a valid 192×192 PWA icon")


if __name__ == "__main__":
    main()
