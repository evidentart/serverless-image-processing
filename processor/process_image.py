"""Create resized JPEGs and an optimized WebP from a local image."""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_FORMATS = {"JPEG", "PNG"}
MAX_IMAGE_DIMENSION = 10_000
MAX_IMAGE_PIXELS = 25_000_000
THUMBNAIL_SIZE = (200, 200)
MEDIUM_SIZE = (800, 800)

# Do not allow Pillow to silently accept truncated image data, and make its
# decompression-bomb threshold match the explicit application limit.
ImageFile.LOAD_TRUNCATED_IMAGES = False
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


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


def _validate_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ImageProcessingError(
            f"Image dimensions exceed the {MAX_IMAGE_DIMENSION}px limit: "
            f"{width}x{height}."
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageProcessingError(
            f"Image pixel count exceeds the {MAX_IMAGE_PIXELS:,} pixel limit: "
            f"{width * height:,}."
        )


def _load_validated_image(input_path: Path, *, require_supported_extension: bool) -> Image.Image:
    if require_supported_extension:
        _validate_input_path(input_path)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(input_path) as probe:
                if probe.format not in SUPPORTED_FORMATS:
                    raise ImageProcessingError(
                        f"Unsupported image content '{probe.format or '(unknown)'}'."
                    )
                _validate_dimensions(probe)
                probe.verify()

            with Image.open(input_path) as source:
                if source.format not in SUPPORTED_FORMATS:
                    raise ImageProcessingError(
                        f"Unsupported image content '{source.format or '(unknown)'}'."
                    )
                _validate_dimensions(source)
                oriented = ImageOps.exif_transpose(source)
                oriented.load()
                return oriented.copy()
    except ImageProcessingError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as error:
        raise ImageProcessingError(
            f"Could not read '{input_path}' as a valid, safe JPG or PNG image."
        ) from error


def load_validated_image(input_path: str | Path) -> Image.Image:
    """Load an image by actual content, without trusting its filename."""
    return _load_validated_image(Path(input_path), require_supported_extension=False)


def _write_outputs(image: Image.Image, destination: Path, stem: str) -> dict[str, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    thumbnail_path = destination / f"{stem}_thumbnail.jpg"
    medium_path = destination / f"{stem}_medium.jpg"
    webp_path = destination / f"{stem}_optimized.webp"

    for resized_image, output_path in (
        (_resize(image, THUMBNAIL_SIZE), thumbnail_path),
        (_resize(image, MEDIUM_SIZE), medium_path),
    ):
        jpeg_image = _as_jpeg(resized_image)
        try:
            jpeg_image.save(output_path, format="JPEG", quality=85, optimize=True)
        finally:
            jpeg_image.close()
            resized_image.close()

    webp_image = image if image.mode in ("RGB", "RGBA") else image.convert("RGB")
    try:
        webp_image.save(webp_path, format="WEBP", quality=82, method=6)
    finally:
        if webp_image is not image:
            webp_image.close()

    return {
        "thumbnail": thumbnail_path,
        "medium": medium_path,
        "webp": webp_path,
    }


def transform_image(image: Image.Image, output_dir: str | Path, stem: str = "image") -> dict[str, Path]:
    """Write the existing thumbnail, medium, and WebP transformations."""
    return _write_outputs(image, Path(output_dir), stem)


def _load_image(input_path: Path) -> Image.Image:
    return _load_validated_image(input_path, require_supported_extension=True)


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

    image = _load_image(source_path)
    try:
        return transform_image(image, destination, source_path.stem)
    finally:
        image.close()


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
