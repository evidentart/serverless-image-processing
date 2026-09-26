import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


LAMBDA_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAMBDA_DIRECTORY))

# boto3 is supplied by the AWS Lambda Python runtime. Keep local unit tests
# dependency-light when the development virtual environment does not include it.
if "boto3" not in sys.modules:
    try:
        import boto3  # noqa: F401
    except ModuleNotFoundError:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.client = lambda service_name: None
        sys.modules["boto3"] = boto3_stub

if "botocore.config" not in sys.modules:
    try:
        from botocore.config import Config  # noqa: F401
    except ModuleNotFoundError:
        botocore_stub = types.ModuleType("botocore")
        botocore_config_stub = types.ModuleType("botocore.config")

        class Config:  # noqa: D101
            def __init__(self, signature_version=None, s3=None):
                self.signature_version = signature_version
                self.s3 = s3

        botocore_config_stub.Config = Config
        botocore_stub.config = botocore_config_stub
        sys.modules["botocore"] = botocore_stub
        sys.modules["botocore.config"] = botocore_config_stub

import presign_upload  # noqa: E402


class FakeS3Client:
    def __init__(self) -> None:
        self.arguments = None

    def generate_presigned_post(self, **kwargs):
        self.arguments = kwargs
        return {
            "url": "https://example-bucket.s3.amazonaws.com/",
            "fields": {
                **kwargs["Fields"],
                "key": kwargs["Key"],
                "policy": "policy",
                "x-amz-algorithm": "AWS4-HMAC-SHA256",
                "x-amz-credential": "credential",
                "x-amz-date": "date",
                "x-amz-signature": "signature",
            },
        }


def request(filename: str, content_type: str, size_bytes) -> dict:
    return {
        "body": json.dumps(
            {
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size_bytes,
            }
        )
    }


def response_body(response: dict) -> dict:
    return json.loads(response["body"])


class PresignUploadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.s3_client = FakeS3Client()
        self.bucket_environment = patch.dict(
            presign_upload.os.environ,
            {"IMAGE_BUCKET": "existing-image-bucket"},
            clear=False,
        )
        self.bucket_environment.start()
        self.s3_client_patch = patch.object(presign_upload, "_s3_client", self.s3_client)
        self.s3_client_patch.start()

    def tearDown(self) -> None:
        self.s3_client_patch.stop()
        self.bucket_environment.stop()

    def test_valid_jpeg_returns_presigned_post(self) -> None:
        response = presign_upload.lambda_handler(request("photo.jpeg", "image/jpeg", 1024), None)

        self.assertEqual(response["statusCode"], 200)
        body = response_body(response)
        self.assertEqual(body["expires_in"], 300)
        self.assertTrue(body["object_key"].startswith("incoming/"))
        self.assertTrue(body["object_key"].endswith(".jpg"))
        self.assertNotIn("photo.jpeg", body["object_key"])
        self.assertEqual(body["fields"]["Content-Type"], "image/jpeg")
        self.assertEqual(body["fields"]["x-amz-server-side-encryption"], "AES256")

    def test_valid_png_returns_png_key(self) -> None:
        response = presign_upload.lambda_handler(request("photo.PNG", "image/png", 2048), None)

        self.assertEqual(response["statusCode"], 200)
        self.assertTrue(response_body(response)["object_key"].endswith(".png"))

    def test_invalid_mime_type_is_rejected(self) -> None:
        response = presign_upload.lambda_handler(request("photo.gif", "image/gif", 1024), None)

        self.assertEqual(response["statusCode"], 400)

    def test_mismatched_extension_is_rejected(self) -> None:
        response = presign_upload.lambda_handler(request("photo.png", "image/jpeg", 1024), None)

        self.assertEqual(response["statusCode"], 400)

    def test_unsafe_filename_is_rejected(self) -> None:
        for filename in ("folder/photo.jpg", r"folder\photo.jpg", "photo\x00.jpg", "photo\n.jpg"):
            with self.subTest(filename=filename):
                response = presign_upload.lambda_handler(
                    request(filename, "image/jpeg", 1024), None
                )
                self.assertEqual(response["statusCode"], 400)

    def test_invalid_sizes_are_rejected(self) -> None:
        for size_bytes in (0, -1, "1024", True):
            with self.subTest(size_bytes=size_bytes):
                response = presign_upload.lambda_handler(
                    request("photo.jpg", "image/jpeg", size_bytes), None
                )
                self.assertEqual(response["statusCode"], 400)

    def test_over_25_mib_is_rejected_with_413(self) -> None:
        response = presign_upload.lambda_handler(
            request("photo.jpg", "image/jpeg", presign_upload.MAX_UPLOAD_SIZE + 1), None
        )

        self.assertEqual(response["statusCode"], 413)

    def test_presign_request_has_restrictive_conditions(self) -> None:
        response = presign_upload.lambda_handler(request("photo.jpg", "image/jpeg", 1024), None)

        self.assertEqual(response["statusCode"], 200)
        arguments = self.s3_client.arguments
        self.assertEqual(arguments["Bucket"], "existing-image-bucket")
        self.assertTrue(arguments["Key"].startswith("incoming/"))
        self.assertTrue(arguments["Key"].endswith(".jpg"))
        self.assertNotIn("photo.jpg", arguments["Key"])
        self.assertEqual(arguments["Fields"]["Content-Type"], "image/jpeg")
        self.assertEqual(arguments["Fields"]["x-amz-server-side-encryption"], "AES256")
        self.assertEqual(arguments["ExpiresIn"], 300)
        self.assertIn({"Content-Type": "image/jpeg"}, arguments["Conditions"])
        self.assertIn(
            ["content-length-range", 1, presign_upload.MAX_UPLOAD_SIZE],
            arguments["Conditions"],
        )
        self.assertIn(
            {"x-amz-server-side-encryption": "AES256"}, arguments["Conditions"]
        )

    def test_s3_client_uses_signature_version_4_and_virtual_addressing(self) -> None:
        created_clients = []
        created_client = object()

        def create_client(service_name, **kwargs):
            created_clients.append((service_name, kwargs))
            return created_client

        with patch.object(presign_upload, "_s3_client", None):
            with patch.object(presign_upload.boto3, "client", side_effect=create_client):
                client = presign_upload._get_s3_client()

        self.assertIs(client, created_client)
        service_name, kwargs = created_clients[0]
        self.assertEqual(service_name, "s3")
        self.assertEqual(kwargs["config"].signature_version, "s3v4")
        self.assertEqual(kwargs["config"].s3, {"addressing_style": "virtual"})

    def test_unexpected_presign_error_returns_generic_500(self) -> None:
        with patch.object(
            presign_upload,
            "_get_s3_client",
            side_effect=RuntimeError("sensitive internal detail"),
        ):
            response = presign_upload.lambda_handler(request("photo.jpg", "image/jpeg", 1024), None)

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            response_body(response), {"error": "Unable to create upload request."}
        )
        self.assertNotIn("sensitive internal detail", response["body"])


if __name__ == "__main__":
    unittest.main()
