"""Report processing status and presign access to completed image outputs."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

PROCESSED_PREFIX = "processed/"
PRESIGNED_GET_EXPIRES_SECONDS = 300
UPLOAD_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

_s3_client: Any | None = None


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
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "isBase64Encoded": False,
        "body": json.dumps(body),
    }


def _upload_id(event: Any) -> str | None:
    if not isinstance(event, dict):
        return None

    path_parameters = event.get("pathParameters")
    if not isinstance(path_parameters, dict):
        return None

    upload_id = path_parameters.get("upload_id")
    if not isinstance(upload_id, str) or UPLOAD_ID_PATTERN.fullmatch(upload_id) is None:
        return None
    return upload_id


def output_keys(upload_id: str) -> dict[str, str]:
    """Construct the only processed keys this handler may inspect."""
    if UPLOAD_ID_PATTERN.fullmatch(upload_id) is None:
        raise ValueError("upload_id must be a lowercase 32-character UUID hex value.")

    prefix = f"{PROCESSED_PREFIX}{upload_id}"
    return {
        "thumbnail": f"{prefix}/thumbnail.jpg",
        "medium": f"{prefix}/medium.jpg",
        "webp": f"{prefix}/optimized.webp",
    }


def _error_code(error: ClientError) -> str:
    error_details = error.response.get("Error", {})
    code = error_details.get("Code", "")
    return str(code)


def _is_missing_output_error(error: ClientError) -> bool:
    response_metadata = error.response.get("ResponseMetadata", {})
    status_code = response_metadata.get("HTTPStatusCode")
    code = _error_code(error)
    return status_code in (403, 404) or code in {
        "403",
        "404",
        "AccessDenied",
        "NoSuchKey",
        "NotFound",
    }


def _is_access_denied_error(error: ClientError) -> bool:
    response_metadata = error.response.get("ResponseMetadata", {})
    return response_metadata.get("HTTPStatusCode") == 403 or _error_code(error) in {
        "403",
        "AccessDenied",
    }


def _outputs_exist(s3_client: Any, bucket: str, keys: dict[str, str]) -> bool:
    for key in keys.values():
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if _is_missing_output_error(error):
                if _is_access_denied_error(error):
                    LOGGER.warning("Processed output is unavailable or access was denied.")
                return False
            LOGGER.error("Unable to inspect a processed output due to a storage failure.")
            raise
        except Exception:
            LOGGER.error("Unable to inspect a processed output due to a runtime failure.")
            raise
    return True


def _presigned_outputs(s3_client: Any, bucket: str, keys: dict[str, str]) -> dict[str, str]:
    return {
        output_name: s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=PRESIGNED_GET_EXPIRES_SECONDS,
        )
        for output_name, key in keys.items()
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Return processing status for one server-generated upload ID."""
    del context

    upload_id = _upload_id(event)
    if upload_id is None:
        return _response(400, {"error": "upload_id must be a valid UUID."})

    bucket = os.environ.get("IMAGE_BUCKET")
    if not bucket:
        LOGGER.error("IMAGE_BUCKET is not configured")
        return _response(500, {"error": "Unable to determine processing status."})

    keys = output_keys(upload_id)
    try:
        if not _outputs_exist(_get_s3_client(), bucket, keys):
            return _response(200, {"status": "processing"})

        outputs = _presigned_outputs(_get_s3_client(), bucket, keys)
    except Exception:
        return _response(500, {"error": "Unable to determine processing status."})

    return _response(200, {"status": "complete", "outputs": outputs})
