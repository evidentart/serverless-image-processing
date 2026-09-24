import tempfile
import unittest
from pathlib import Path

from PIL import Image

from processor.process_image import ImageProcessingError, process_image


class ProcessImageTests(unittest.TestCase):
    def create_image(self, directory: Path, name: str, image_format: str, size=(1600, 800)) -> Path:
        image_path = directory / name
        image = Image.new("RGB", size, color=(38, 99, 235))
        image.save(image_path, format=image_format)
        image.close()
        return image_path

    def test_successful_jpeg_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = self.create_image(root, "example.jpg", "JPEG")
            output_dir = root / "output"

            outputs = process_image(input_path, output_dir)

            self.assertEqual(set(outputs), {"thumbnail", "medium", "webp"})
            self.assertTrue(all(path.exists() for path in outputs.values()))
            with Image.open(outputs["thumbnail"]) as thumbnail:
                self.assertEqual(thumbnail.format, "JPEG")
            with Image.open(outputs["webp"]) as webp:
                self.assertEqual(webp.format, "WEBP")

    def test_successful_png_processing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = self.create_image(root, "example.png", "PNG")

            outputs = process_image(input_path, root / "output")

            self.assertTrue(all(path.exists() for path in outputs.values()))
            with Image.open(outputs["medium"]) as medium:
                self.assertEqual(medium.format, "JPEG")

    def test_preserves_aspect_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = self.create_image(root, "wide.jpg", "JPEG", size=(1600, 800))

            outputs = process_image(input_path, root / "output")

            with Image.open(outputs["thumbnail"]) as thumbnail, Image.open(outputs["medium"]) as medium:
                self.assertEqual(thumbnail.size, (200, 100))
                self.assertEqual(medium.size, (800, 400))

    def test_rejects_unsupported_file_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "example.gif"
            input_path.write_bytes(b"not a supported image")

            with self.assertRaisesRegex(ImageProcessingError, "Unsupported image type"):
                process_image(input_path, Path(temporary_directory) / "output")


if __name__ == "__main__":
    unittest.main()
