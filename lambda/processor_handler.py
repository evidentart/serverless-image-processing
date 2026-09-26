"""Process validated images delivered from S3 through an SQS event."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote_plus

import boto3

from processor.process_image import ImageProcessingError, load_validated_image, transform_image


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

MAX_UPLOAD_SIZE = 25 * 1024 * 1024
INCOMING_PREFIX = "incoming/"
PROCESSED_PREFIX = "processed/"
UUID_KEY_PATTERN = re.compile(r"^(?P<source_id>[0-9a-f]{32})(?:\.[^/]*)?$")


class InvalidEvent(ValueError):
    """An SQS or S3 event that cannot be safely processed."""


class InvalidImage(ValueError):
    """An image that is too large, malformed, or otherwise unsafe."""


def _json_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidEvent(f"{description} must be an object.")
    return value


def _is_s3_test_event(message: dict[str, Any]) -> bool:
    required_fields = ("Time", "Bucket", "RequestId", "HostId")
    return (
        message.get("Service") == "Amazon S3"
        and message.get("Event") == "s3:TestEvent"
        and all(
            isinstance(message.get(field), str) and bool(message[field].strip())
            for field in required_fields
        )
    )


def _s3_records(event: Any) -> Iterator[dict[str, Any]]:
    event_object = _json_object(event, "Lambda event")
    records = event_object.get("Records")
    if not isinstance(records, list) or not records:
        raise InvalidEvent("Lambda event must contain SQS records.")

    for sqs_record in records:
        sqs_object = _json_object(sqs_record, "SQS record")
        body = sqs_object.get("body")
        if not isinstance(body, str) or not body:
            raise InvalidEvent("SQS record body must be a non-empty string.")
        try:
            message = json.loads(body)
        except json.JSONDecodeError as error:
            raise InvalidEvent("SQS record body must contain valid JSON.") from error

        message_object = _json_object(message, "S3 event")
        if _is_s3_test_event(message_object):
            continue

        embedded_records = message_object.get("Records")
        if not isinstance(embedded_records, list) or not embedded_records:
            raise InvalidEvent("S3 event must contain records.")
        for embedded_record in embedded_records:
            yield _json_object(embedded_record, "S3 record")


def _source_details(record: dict[str, Any], expected_bucket: str) -> tuple[str, str]:
    event_name = record.get("eventName")
    if not isinstance(event_name, str) or not event_name.startswith("ObjectCreated:"):
        raise InvalidEvent("S3 record is not an object-created event.")

    s3_object = _json_object(record.get("s3"), "S3 record payload")
    bucket_object = _json_object(s3_object.get("bucket"), "S3 bucket payload")
    bucket_name = bucket_object.get("name")
    if bucket_name != expected_bucket:
        raise InvalidEvent("S3 record bucket does not match the configured bucket.")

    object_object = _json_object(s3_object.get("object"), "S3 object payload")
    encoded_key = object_object.get("key")
    if not isinstance(encoded_key, str) or not encoded_key:
        raise InvalidEvent("S3 object key must be a non-empty string.")

    key = unquote_plus(encoded_key)
    if "\x00" in key or not key.startswith(INCOMING_PREFIX):
        raise InvalidEvent("S3 object key is outside the incoming prefix.")

    relative_key = key[len(INCOMING_PREFIX):]
    if "/" in relative_key:
        raise InvalidEvent("S3 object key has an unsafe path.")
    source_match = UUID_KEY_PATTERN.fullmatch(relative_key)
    if source_match is None:
        raise InvalidEvent("S3 object key does not contain a generated UUID.")

    return key, source_match.group("source_id")


def output_keys(source_id: str) -> dict[str, str]:
    """Return deterministic output keys for a generated source UUID."""
    if re.fullmatch(r"[0-9a-f]{32}", source_id) is None:
        raise ValueError("source_id must be a lowercase 32-character UUID hex value.")
    prefix = f"{PROCESSED_PREFIX}{source_id}"
    return {
        "thumbnail": f"{prefix}/thumbnail.jpg",
        "medium": f"{prefix}/medium.jpg",
        "webp": f"{prefix}/optimized.webp",
    }


def _download_object(s3_client: Any, bucket: str, key: str, destination: Path) -> None:
    head = s3_client.head_object(Bucket=bucket, Key=key)
    content_length = head.get("ContentLength")
    if isinstance(content_length, bool) or not isinstance(content_length, int):
        raise InvalidImage("S3 object size is missing or invalid.")
    if content_length <= 0 or content_length > MAX_UPLOAD_SIZE:
        raise InvalidImage("S3 object exceeds the 25 MiB upload limit.")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response.get("Body")
    if body is None or not hasattr(body, "read"):
        raise RuntimeError("S3 object response did not contain a readable body.")

    bytes_written = 0
    try:
        with destination.open("wb") as output_file:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_SIZE:
                    raise InvalidImage("S3 object exceeds the 25 MiB upload limit.")
                output_file.write(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()

    if bytes_written != content_length:
        raise InvalidImage("S3 object size changed during download.")


def _upload_outputs(
    s3_client: Any,
    bucket: str,
    output_paths: dict[str, Path],
    source_id: str,
) -> None:
    keys = output_keys(source_id)
    content_types = {
        "thumbnail": "image/jpeg",
        "medium": "image/jpeg",
        "webp": "image/webp",
    }
    for output_name, output_path in output_paths.items():
        with output_path.open("rb") as output_file:
            s3_client.put_object(
                Bucket=bucket,
                Key=keys[output_name],
                Body=output_file,
                ContentType=content_types[output_name],
                ServerSideEncryption="AES256",
            )


def _process_record(s3_client: Any, bucket: str, record: dict[str, Any]) -> None:
    key, source_id = _source_details(record, bucket)
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_path = Path(temporary_directory)
        source_path = temporary_path / "source-image"
        output_directory = temporary_path / "outputs"
        _download_object(s3_client, bucket, key, source_path)

        try:
            image = load_validated_image(source_path)
        except ImageProcessingError as error:
            raise InvalidImage("S3 object is not a valid safe JPEG or PNG image.") from error

        try:
            outputs = transform_image(image, output_directory, "output")
        finally:
            image.close()
        _upload_outputs(s3_client, bucket, outputs, source_id)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """Process one-SQS-message batches and let failures return to SQS."""
    del context

    bucket = os.environ.get("IMAGE_BUCKET")
    if not bucket:
        raise RuntimeError("IMAGE_BUCKET is not configured.")

    s3_client = boto3.client("s3")
    processed_count = 0
    for record in _s3_records(event):
        _process_record(s3_client, bucket, record)
        processed_count += 1

    return {"processed_records": processed_count}
