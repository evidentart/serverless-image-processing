# Serverless Image Processing Platform

A portfolio project demonstrating a serverless image-upload and processing pipeline. Phase 4 is deployed and verified end to end.

## Current architecture

```text
React/Vite frontend
        |
        v
API Gateway HTTP API
        |
        v
Presign Lambda
        |
        v
Browser direct upload to S3 incoming/
        |
        v
S3 ObjectCreated notification
        |
        v
Standard SQS processing queue
        |
        v
Processing Lambda with Pillow
        |
        v
S3 processed/<uuid>/
```

Image bytes upload directly from the browser to the private S3 bucket; they do not pass through Lambda or API Gateway. The presign Lambda creates short-lived upload policies, while the processing Lambda consumes validated event messages asynchronously.

## Upload and processing outputs

Phase 3 accepts JPEG/JPG and PNG uploads up to 25 MiB. S3 object keys use server-generated UUIDs and never use original filenames.

A successfully processed image produces deterministic outputs such as:

```text
processed/<uuid>/thumbnail.jpg
processed/<uuid>/medium.jpg
processed/<uuid>/optimized.webp
```

## Security controls

- The S3 bucket is private with S3 Block Public Access and `BucketOwnerEnforced` ownership.
- SSE-S3 AES256 encryption and a TLS-only bucket policy are enabled.
- Presigned POST policies expire after five minutes and enforce size, `Content-Type`, generated key, and AES256 conditions.
- The presign Lambda has `s3:PutObject` only to `incoming/*`.
- The processing Lambda reads only from `incoming/*` and writes only to `processed/*`.
- The processing Lambda does not delete source objects, list the bucket, or write back to `incoming/*`.
- The processing Lambda consumes only the processing SQS queue.
- The processing Lambda has no VPC, NAT Gateway, reserved concurrency, or provisioned concurrency.
- Original filenames are not used as local processing paths or processed S3 keys.
- The frontend does not display or log signed AWS fields.

## Image validation

Phase 4 validates actual image content with Pillow instead of trusting MIME metadata or file extensions. It includes:

- Actual JPEG and PNG content validation
- `Image.verify()` followed by reopening the image for processing
- Truncated-image rejection
- Pillow decompression-bomb protection
- Maximum dimension of 10,000 pixels
- Maximum total pixel count of 25,000,000
- EXIF orientation handling
- Generated safe temporary paths under `/tmp`
- No use of original user filenames as processing paths or processed keys

## SQS and failure handling

- Standard SQS processing queue with batch size 1
- Maximum event-source concurrency of 2
- 360-second visibility timeout
- Four-day main queue retention
- Dead-letter queue after three receives
- 14-day DLQ retention
- SQS-managed encryption
- Deterministic output paths make duplicate deliveries safe
- Malformed or transient failures retry through SQS and eventually move to the DLQ
- S3 `s3:TestEvent` messages are explicitly handled as harmless successful no-ops

The S3 notification is filtered to `incoming/`, so objects written under `processed/` cannot recursively trigger processing. The existing development lifecycle rule applies to the entire bucket: both `incoming/*` and `processed/*` expire after 30 days. This is intentional for the temporary portfolio/dev environment.

## Packaging

Before any Terraform plan or apply involving processor Lambda code, run:

```powershell
.\scripts\build_processor_lambda.ps1
```

Terraform archives the generated, Git-ignored `.phase4-build/processor-package` directory. A clean checkout must run this reproducible build step first. The script packages Linux/x86_64-compatible Pillow wheels for the Python 3.12 Lambda runtime and does not copy Pillow from the Windows virtual environment.

## Testing and verification

Verified Phase 4 results:

- 10 presign Lambda tests pass
- 16 processor-handler Lambda tests pass
- 4 processor tests pass
- 30 total Python tests pass
- Terraform fmt check passes
- Terraform validate passes
- Terraform reports no infrastructure drift after deployment
- The live processor Lambda is Active
- The live SQS event source mapping is Enabled
- A real JPEG was uploaded to `incoming/`
- The live pipeline produced `thumbnail.jpg`, `medium.jpg`, and `optimized.webp`
- The main queue and DLQ were clean after testing

## Current limitations and future work

- The upload API remains unauthenticated for the current development/portfolio phase.
- API throttling reduces abuse risk but is not a hard security boundary or spending cap.
- The frontend does not yet display processed results or processing status.
- CORS currently allows only the local Vite origins.
- Terraform state is still local.
- Direct `AdministratorAccess` remains a temporary bootstrap compromise, not the desired long-term deployment model.
- Production frontend hosting and CI/CD are not implemented yet.
- The project is not complete until these operational limitations are addressed for a production deployment.

## Cost and architectural decisions

- Serverless, pay-per-use services are used throughout.
- HTTP API was selected instead of REST API.
- Direct browser-to-S3 upload avoids sending image bytes through Lambda.
- SQS provides decoupling, retries, and DLQ handling without an always-on worker.
- No DynamoDB, EventBridge, VPC, NAT Gateway, WAF, Cognito, ECR, or customer-managed KMS key is used.
- S3 versioning is intentionally disabled for disposable development image objects.
- AWS Budget alerts provide visibility but are not a hard spending cap.
