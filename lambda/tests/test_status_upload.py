import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


LAMBDA_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAMBDA_DIRECTORY))

# boto3 and botocore are supplied by the AWS Lambda Python runtime. Keep local
# unit tests dependency-light when the development virtual environment does
# not include them.
if "boto3" not in sys.modules:
    try:
        import boto3  # noqa: F401
    except ModuleNotFoundError:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.client = lambda service_name: None
        sys.modules["boto3"] = boto3_stub

try:
    from botocore.exceptions import ClientError
except ModuleNotFoundError:
    if "botocore" not in sys.modules:
        sys.modules["botocore"] = types.ModuleType("botocore")
    botocore_exceptions_stub = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):  # noqa: D101
        def __init__(self, error_response, operation_name):
            super().__init__(str(error_response))
            self.response = error_response
            self.operation_name = operation_name

    botocore_exceptions_stub.ClientError = ClientError
    sys.modules["botocore.exceptions"] = botocore_exceptions_stub

if "botocore.config" not in sys.modules:
    try:
        from botocore.config import Config  # noqa: F401
    except ModuleNotFoundError:
        botocore_config_stub = types.ModuleType("botocore.config")

        class Config:  # noqa: D101
            def __init__(self, signature_version=None, s3=None):
                self.signature_version = signature_version
                self.s3 = s3

        botocore_config_stub.Config = Config
        sys.modules["botocore.config"] = botocore_config_stub

import status_upload  # noqa: E402


BUCKET_NAME = "existing-image-bucket"
UPLOAD_ID = "0123456789abcdef0123456789abcdef"
OUTPUT_KEYS = {
    "thumbnail": f"processed/{UPLOAD_ID}/thumbnail.jpg",
    "medium": f"processed/{UPLOAD_ID}/medium.jpg",
    "webp": f"processed/{UPLOAD_ID}/optimized.webp",
}


def event(upload_id: str | None = UPLOAD_ID) -> dict:
    if upload_id is None:
        return {"pathParameters": {}}
    return {"pathParameters": {"upload_id": upload_id}}


def response_body(response: dict) -> dict:
    return json.loads(response["body"])


def client_error(code: str, status_code: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "test error"},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        },
        "HeadObject",
    )


class FakeS3Client:
    def __init__(self, head_errors: dict[str, ClientError] | None = None) -> None:
        self.head_errors = head_errors or {}
        self.head_calls: list[dict[str, str]] = []
        self.presign_calls: list[dict] = []

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        error = self.head_errors.get(kwargs["Key"])
        if error is not None:
            raise error
        return {"ContentLength": 1}

    def generate_presigned_url(self, **kwargs) -> str:
        self.presign_calls.append(kwargs)
        return f"https://example.com/{kwargs['Params']['Key']}"


class StatusUploadTests(unittest.TestCase):
    def run_handler(self, client: FakeS3Client, request: object) -> dict:
        with patch.dict(status_upload.os.environ, {"IMAGE_BUCKET": BUCKET_NAME}):
            with patch.object(status_upload, "_s3_client", client):
                return status_upload.lambda_handler(request, None)

    def test_s3_client_uses_signature_version_4_and_virtual_addressing(self) -> None:
        created_clients = []
        created_client = object()

        def create_client(service_name, **kwargs):
            created_clients.append((service_name, kwargs))
            return created_client

        with patch.object(status_upload, "_s3_client", None):
            with patch.object(status_upload.boto3, "client", side_effect=create_client):
                client = status_upload._get_s3_client()

        self.assertIs(client, created_client)
        service_name, kwargs = created_clients[0]
        self.assertEqual(service_name, "s3")
        self.assertEqual(kwargs["config"].signature_version, "s3v4")
        self.assertEqual(kwargs["config"].s3, {"addressing_style": "virtual"})

    def test_output_keys_are_exactly_server_constructed(self) -> None:
        self.assertEqual(status_upload.output_keys(UPLOAD_ID), OUTPUT_KEYS)

    def test_missing_upload_id_is_rejected(self) -> None:
        response = self.run_handler(FakeS3Client(), event(None))

        self.assertEqual(response["statusCode"], 400)

    def test_malformed_events_are_rejected(self) -> None:
        malformed_events = (
            {},
            {"pathParameters": None},
            {"pathParameters": {"upload_id": 123}},
            None,
        )

        for request in malformed_events:
            with self.subTest(request=request):
                client = FakeS3Client()
                response = self.run_handler(client, request)

                self.assertEqual(response["statusCode"], 400)
                self.assertFalse(client.head_calls)

    def test_invalid_upload_id_is_rejected(self) -> None:
        for upload_id in (
            "0123456789ABCDEF0123456789abcdef",
            "0123456789abcdef0123456789abcde",
            "0123456789abcdef0123456789abcdef0",
            f"processed/{UPLOAD_ID}",
            f"{UPLOAD_ID}.jpg",
        ):
            with self.subTest(upload_id=upload_id):
                response = self.run_handler(FakeS3Client(), event(upload_id))
                self.assertEqual(response["statusCode"], 400)

    def test_missing_output_returns_processing_and_short_circuits(self) -> None:
        client = FakeS3Client(
            {OUTPUT_KEYS["thumbnail"]: client_error("NoSuchKey", 404)}
        )

        response = self.run_handler(client, event())

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response_body(response), {"status": "processing"})
        self.assertEqual(
            client.head_calls,
            [{"Bucket": BUCKET_NAME, "Key": OUTPUT_KEYS["thumbnail"]}],
        )
        self.assertFalse(client.presign_calls)

    def test_http_404_returns_processing(self) -> None:
        client = FakeS3Client(
            {OUTPUT_KEYS["thumbnail"]: client_error("404", 404)}
        )

        response = self.run_handler(client, event())

        self.assertEqual(response_body(response), {"status": "processing"})

    def test_http_403_returns_processing_without_urls(self) -> None:
        client = FakeS3Client(
            {OUTPUT_KEYS["thumbnail"]: client_error("AccessDenied", 403)}
        )

        response = self.run_handler(client, event())

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response_body(response), {"status": "processing"})
        self.assertFalse(client.presign_calls)

    def test_partial_outputs_return_processing_and_short_circuit(self) -> None:
        client = FakeS3Client(
            {OUTPUT_KEYS["medium"]: client_error("NotFound", 404)}
        )

        response = self.run_handler(client, event())

        self.assertEqual(response_body(response), {"status": "processing"})
        self.assertEqual(
            [call["Key"] for call in client.head_calls],
            [OUTPUT_KEYS["thumbnail"], OUTPUT_KEYS["medium"]],
        )
        self.assertFalse(client.presign_calls)

    def test_all_outputs_return_complete_with_five_minute_urls(self) -> None:
        client = FakeS3Client()

        response = self.run_handler(client, event())

        self.assertEqual(response["statusCode"], 200)
        body = response_body(response)
        self.assertEqual(body["status"], "complete")
        self.assertEqual(
            body["outputs"],
            {name: f"https://example.com/{key}" for name, key in OUTPUT_KEYS.items()},
        )
        self.assertEqual(
            [call["Params"]["Key"] for call in client.presign_calls],
            list(OUTPUT_KEYS.values()),
        )
        for output_name, call in zip(OUTPUT_KEYS, client.presign_calls):
            with self.subTest(output_name=output_name):
                self.assertEqual(call["ClientMethod"], "get_object")
                self.assertEqual(call["Params"]["Bucket"], BUCKET_NAME)
                self.assertEqual(call["Params"]["Key"], OUTPUT_KEYS[output_name])
                self.assertEqual(call["ExpiresIn"], 300)

    def test_presigned_url_generation_failure_returns_generic_service_error(self) -> None:
        client = FakeS3Client()
        with patch.object(
            client,
            "generate_presigned_url",
            side_effect=RuntimeError("sensitive presign detail"),
        ):
            response = self.run_handler(client, event())

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            response_body(response),
            {"error": "Unable to determine processing status."},
        )
        self.assertNotIn("sensitive presign detail", response["body"])
        self.assertNotIn("outputs", response_body(response))

    def test_unexpected_s3_error_returns_generic_service_error(self) -> None:
        client = FakeS3Client(
            {OUTPUT_KEYS["thumbnail"]: client_error("InternalError", 500)}
        )

        response = self.run_handler(client, event())

        self.assertEqual(response["statusCode"], 500)
        self.assertEqual(
            response_body(response),
            {"error": "Unable to determine processing status."},
        )
        self.assertNotIn("InternalError", response["body"])
        self.assertFalse(client.presign_calls)

    def test_responses_disable_caching(self) -> None:
        response = self.run_handler(FakeS3Client(), event())

        self.assertEqual(response["headers"]["Cache-Control"], "no-store")


if __name__ == "__main__":
    unittest.main()
