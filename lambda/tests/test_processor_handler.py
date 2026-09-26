import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote_plus

from PIL import Image


LAMBDA_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_DIRECTORY = LAMBDA_DIRECTORY.parent
sys.path.insert(0, str(LAMBDA_DIRECTORY))
sys.path.insert(0, str(PROJECT_DIRECTORY))

if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda service_name: None
    sys.modules["boto3"] = boto3_stub

import processor_handler  # noqa: E402
from processor.process_image import MAX_IMAGE_PIXELS  # noqa: E402


BUCKET_NAME = "existing-image-bucket"
SOURCE_ID = "0123456789abcdef0123456789abcdef"


def image_bytes(image_format: str, size: tuple[int, int] = (160, 80), mode: str = "RGB") -> bytes:
    image = Image.new(mode, size, color=(38, 99, 235))
    output = io.BytesIO()
    image.save(output, format=image_format)
    image.close()
    return output.getvalue()


def s3_event(key: str, size: int | None = None) -> dict:
    object_payload = {"key": quote_plus(key)}
    if size is not None:
        object_payload["size"] = size
    return {
        "Records": [
            {
                "eventName": "ObjectCreated:Post",
                "s3": {
                    "bucket": {"name": BUCKET_NAME},
                    "object": object_payload,
                },
            }
        ]
    }


def sqs_event(message: dict) -> dict:
    return {"Records": [{"messageId": "message-1", "body": json.dumps(message)}]}


def s3_test_event() -> dict:
    return {
        "Service": "Amazon S3",
        "Event": "s3:TestEvent",
        "Time": "2026-09-26T00:00:00.000Z",
        "Bucket": BUCKET_NAME,
        "RequestId": "request-id",
        "HostId": "host-id",
    }


class FakeBody(io.BytesIO):
    pass


class FakeS3Client:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.uploads: dict[str, bytes] = {}
        self.put_arguments: list[dict] = []

    def head_object(self, Bucket: str, Key: str) -> dict:
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": FakeBody(self.objects[Key])}

    def put_object(self, **kwargs) -> dict:
        self.put_arguments.append(kwargs)
        body = kwargs["Body"]
        self.uploads[kwargs["Key"]] = body.read()
        return {}


class ProcessorHandlerTests(unittest.TestCase):
    def run_handler(self, client: FakeS3Client, event: dict) -> dict:
        with patch.dict(processor_handler.os.environ, {"IMAGE_BUCKET": BUCKET_NAME}):
            with patch.object(processor_handler.boto3, "client", return_value=client):
                return processor_handler.lambda_handler(event, None)

    def test_valid_jpeg_is_transformed(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG")})

        result = self.run_handler(client, sqs_event(s3_event(key)))

        self.assertEqual(result, {"processed_records": 1})
        self.assertEqual(
            set(client.uploads),
            {
                f"processed/{SOURCE_ID}/thumbnail.jpg",
                f"processed/{SOURCE_ID}/medium.jpg",
                f"processed/{SOURCE_ID}/optimized.webp",
            },
        )
        self.assertEqual(len(client.put_arguments), 3)
        self.assertTrue(all(argument["ServerSideEncryption"] == "AES256" for argument in client.put_arguments))

    def test_valid_png_transparency_is_supported(self) -> None:
        key = f"incoming/{SOURCE_ID}.png"
        client = FakeS3Client({key: image_bytes("PNG", mode="RGBA")})

        self.run_handler(client, sqs_event(s3_event(key)))

        with Image.open(io.BytesIO(client.uploads[f"processed/{SOURCE_ID}/thumbnail.jpg"])) as thumbnail:
            self.assertEqual(thumbnail.format, "JPEG")
            self.assertEqual(thumbnail.mode, "RGB")
        with Image.open(io.BytesIO(client.uploads[f"processed/{SOURCE_ID}/optimized.webp"])) as webp:
            self.assertEqual(webp.format, "WEBP")

    def test_corrupt_image_fails(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: b"not an image"})

        with self.assertRaises(processor_handler.InvalidImage):
            self.run_handler(client, sqs_event(s3_event(key)))
        self.assertFalse(client.uploads)

    def test_unsupported_actual_format_fails_even_with_image_extension(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("GIF")})

        with self.assertRaises(processor_handler.InvalidImage):
            self.run_handler(client, sqs_event(s3_event(key)))

    def test_valid_content_is_used_instead_of_extension(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("PNG")})

        self.run_handler(client, sqs_event(s3_event(key)))

        self.assertIn(f"processed/{SOURCE_ID}/optimized.webp", client.uploads)

    def test_invalid_sqs_event_fails(self) -> None:
        client = FakeS3Client({})

        with self.assertRaises(processor_handler.InvalidEvent):
            self.run_handler(client, {})

    def test_invalid_embedded_s3_event_fails(self) -> None:
        client = FakeS3Client({})

        with self.assertRaises(processor_handler.InvalidEvent):
            self.run_handler(client, sqs_event({"Records": [{}]}))

    def test_valid_s3_test_event_is_a_noop(self) -> None:
        client = FakeS3Client({})

        result = self.run_handler(client, sqs_event(s3_test_event()))

        self.assertEqual(result, {"processed_records": 0})
        self.assertFalse(client.uploads)

    def test_s3_test_event_missing_required_field_fails(self) -> None:
        for field in ("Time", "Bucket", "RequestId", "HostId"):
            with self.subTest(field=field):
                message = s3_test_event()
                del message[field]
                with self.assertRaises(processor_handler.InvalidEvent):
                    self.run_handler(FakeS3Client({}), sqs_event(message))

    def test_s3_test_event_empty_required_field_fails(self) -> None:
        for field in ("Time", "Bucket", "RequestId", "HostId"):
            with self.subTest(field=field):
                message = s3_test_event()
                message[field] = "  "
                with self.assertRaises(processor_handler.InvalidEvent):
                    self.run_handler(FakeS3Client({}), sqs_event(message))

    def test_malformed_non_test_event_without_records_fails(self) -> None:
        client = FakeS3Client({})

        with self.assertRaises(processor_handler.InvalidEvent):
            self.run_handler(
                client,
                sqs_event({"Service": "Amazon S3", "Event": "s3:OtherEvent"}),
            )

    def test_non_incoming_key_fails(self) -> None:
        key = f"processed/{SOURCE_ID}/thumbnail.jpg"
        client = FakeS3Client({key: image_bytes("JPEG")})

        with self.assertRaises(processor_handler.InvalidEvent):
            self.run_handler(client, sqs_event(s3_event(key)))

    def test_oversized_s3_object_is_rejected_before_download(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG")})

        with patch.object(client, "head_object", return_value={"ContentLength": 25 * 1024 * 1024 + 1}):
            with self.assertRaises(processor_handler.InvalidImage):
                self.run_handler(client, sqs_event(s3_event(key)))

        self.assertFalse(client.uploads)

    def test_excessive_dimensions_are_rejected(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG", size=(10_001, 1))})

        with self.assertRaises(processor_handler.InvalidImage):
            self.run_handler(client, sqs_event(s3_event(key)))

    def test_excessive_pixel_count_is_rejected(self) -> None:
        self.assertEqual(MAX_IMAGE_PIXELS, 25_000_000)
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG", size=(5_001, 5_000))})

        with self.assertRaises(processor_handler.InvalidImage):
            self.run_handler(client, sqs_event(s3_event(key)))

    def test_decompression_bomb_error_is_rejected(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG")})

        with patch(
            "processor.process_image.Image.open",
            side_effect=Image.DecompressionBombError("bomb"),
        ):
            with self.assertRaises(processor_handler.InvalidImage):
                self.run_handler(client, sqs_event(s3_event(key)))

    def test_output_keys_are_deterministic(self) -> None:
        first = processor_handler.output_keys(SOURCE_ID)
        second = processor_handler.output_keys(SOURCE_ID)

        self.assertEqual(first, second)
        self.assertEqual(first["thumbnail"], f"processed/{SOURCE_ID}/thumbnail.jpg")

    def test_duplicate_delivery_overwrites_same_outputs(self) -> None:
        key = f"incoming/{SOURCE_ID}.jpg"
        client = FakeS3Client({key: image_bytes("JPEG")})
        event = sqs_event(s3_event(key))

        self.run_handler(client, event)
        first_uploads = dict(client.uploads)
        self.run_handler(client, event)

        self.assertEqual(client.uploads, first_uploads)
        self.assertEqual(len(client.uploads), 3)


if __name__ == "__main__":
    unittest.main()
