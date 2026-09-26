"""Create short-lived S3 presigned POST policies for image uploads."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import uuid
from pathlib import PurePath
from typing import Any

import boto3
from botocore.config import Config


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

MAX_UPLOAD_SIZE = 25 * 1024 * 1024
PRESIGN_EXPIRES_SECONDS = 300
UPLOAD_PREFIX = "incoming/"
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
}
KEY_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
}

_s3_client: Any | None = None


class InvalidRequest(ValueError):
    """A request that cannot receive an upload policy."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _get_s3_client() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )
    return _s3_client


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "isBase64Encoded": False,
        "body": json.dumps(body),
    }


def _request_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") if isinstance(event, dict) else None
    if isinstance(event, dict) and event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body or "", validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as error:
            raise InvalidRequest("Request body must be valid JSON.") from error

    if isinstance(body, dict):
        return body
    if not isinstance(body, str) or not body.strip():
        raise InvalidRequest("Request body must be a JSON object.")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise InvalidRequest("Request body must be valid JSON.") from error

    if not isinstance(parsed, dict):
        raise InvalidRequest("Request body must be a JSON object.")
    return parsed


def _validate_request(payload: dict[str, Any]) -> tuple[str, str, int]:
    filename = payload.get("filename")
    content_type = payload.get("content_type")
    size_bytes = payload.get("size_bytes")

    if not isinstance(filename, str) or not filename:
        raise InvalidRequest("filename must be a non-empty string.")
    if len(filename) > 255:
        raise InvalidRequest("filename must not exceed 255 characters.")
    if any(character in filename for character in ("/", "\\", "\x00")):
        raise InvalidRequest("filename contains an invalid path character.")
    if any(ord(character) < 32 or ord(character) == 127 for character in filename):
        raise InvalidRequest("filename contains a control character.")

    if not isinstance(content_type, str) or content_type not in CONTENT_TYPE_EXTENSIONS:
        raise InvalidRequest("content_type must be image/jpeg or image/png.")

    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
        raise InvalidRequest("size_bytes must be an integer.")
    if size_bytes <= 0:
        raise InvalidRequest("size_bytes must be greater than zero.")
    if size_bytes > MAX_UPLOAD_SIZE:
        raise InvalidRequest("size_bytes exceeds the 25 MiB limit.", status_code=413)

    extension = PurePath(filename).suffix.lower()
    if extension not in CONTENT_TYPE_EXTENSIONS[content_type]:
        raise InvalidRequest("filename extension does not match content_type.")

    return filename, content_type, size_bytes


def _generate_object_key(content_type: str) -> str:
    return f"{UPLOAD_PREFIX}{uuid.uuid4().hex}.{KEY_EXTENSIONS[content_type]}"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context

    try:
        payload = _request_body(event)
        _, content_type, _ = _validate_request(payload)
    except InvalidRequest as error:
        return _response(error.status_code, {"error": str(error)})

    bucket_name = os.environ.get("IMAGE_BUCKET")
    if not bucket_name:
        LOGGER.error("IMAGE_BUCKET is not configured")
        return _response(500, {"error": "Unable to create upload request."})

    object_key = _generate_object_key(content_type)
    fields = {
        "Content-Type": content_type,
        "x-amz-server-side-encryption": "AES256",
    }
    conditions = [
        {"Content-Type": content_type},
        ["content-length-range", 1, MAX_UPLOAD_SIZE],
        {"x-amz-server-side-encryption": "AES256"},
    ]

    try:
        presigned_post = _get_s3_client().generate_presigned_post(
            Bucket=bucket_name,
            Key=object_key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=PRESIGN_EXPIRES_SECONDS,
        )
    except Exception:
        LOGGER.exception("Unable to create an S3 presigned POST")
        return _response(500, {"error": "Unable to create upload request."})

    return _response(
        200,
        {
            "upload_url": presigned_post["url"],
            "object_key": object_key,
            "expires_in": PRESIGN_EXPIRES_SECONDS,
            "fields": presigned_post["fields"],
        },
    )
