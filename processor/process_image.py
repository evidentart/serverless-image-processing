"""Create resized JPEGs and an optimized WebP from a local image."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
THUMBNAIL_SIZE = (200, 200)
MEDIUM_SIZE = (800, 800)


class ImageProcessingError(ValueError):
    """An expected, user-facing image processing error."""


def _validate_input_path(input_path: Path) -> None:
    if not input_path.exists():
        raise ImageProcessingError(f"Input image does not exist: {input_path}")

    if not input_path.is_file():
        raise ImageProcessingError(f"Input path is not a file: {input_path}")

    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ImageProcessingError(
            f"Unsupported image type '{input_path.suffix or '(none)'}'. "
            f"Please provide a JPG or PNG file ({supported})."
        )


def _load_image(input_path: Path) -> Image.Image:
    _validate_input_path(input_path)

    try:
        with Image.open(input_path) as source:
            source.load()
            return ImageOps.exif_transpose(source).copy()
    except (UnidentifiedImageError, OSError) as error:
        raise ImageProcessingError(
            f"Could not read '{input_path}' as a valid JPG or PNG image."
        ) from error


def _as_jpeg(image: Image.Image) -> Image.Image:
    """Return an RGB image, compositing transparency over a white background."""
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba_image = image.convert("RGBA")
        background = Image.new("RGB", rgba_image.size, "white")
        background.paste(rgba_image, mask=rgba_image.getchannel("A"))
        return background
    return image.convert("RGB")


def _resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    resized = image.copy()
    resized.thumbnail(size, Image.Resampling.LANCZOS)
    return resized


def process_image(input_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    """Process a local JPG or PNG and return the generated output paths.

    Thumbnail and medium images are JPEGs. The optimized output is WebP.
    Existing smaller images are not upscaled, and all outputs preserve aspect ratio.
    """
    source_path = Path(input_path)
    destination = Path(output_dir) if output_dir is not None else Path(__file__).parent / "output"
    destination.mkdir(parents=True, exist_ok=True)

    image = _load_image(source_path)
    try:
        stem = source_path.stem
        thumbnail_path = destination / f"{stem}_thumbnail.jpg"
        medium_path = destination / f"{stem}_medium.jpg"
        webp_path = destination / f"{stem}_optimized.webp"

        _as_jpeg(_resize(image, THUMBNAIL_SIZE)).save(
            thumbnail_path, format="JPEG", quality=85, optimize=True
        )
        _as_jpeg(_resize(image, MEDIUM_SIZE)).save(
            medium_path, format="JPEG", quality=85, optimize=True
        )

        webp_image = image if image.mode in ("RGB", "RGBA") else image.convert("RGB")
        webp_image.save(webp_path, format="WEBP", quality=82, method=6)
    finally:
        image.close()

    return {
        "thumbnail": thumbnail_path,
        "medium": medium_path,
        "webp": webp_path,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate thumbnail, medium, and optimized WebP images."
    )
    parser.add_argument("input", type=Path, help="Path to a local JPG or PNG image")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output",
        help="Directory for generated images (default: processor/output)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        outputs = process_image(args.input, args.output_dir)
    except ImageProcessingError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Processed: {args.input}")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
