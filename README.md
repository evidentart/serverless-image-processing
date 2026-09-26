# Serverless Image Processing Platform

A portfolio project for a serverless image-upload and processing platform. Phase 3 is complete: the React/Vite frontend requests a short-lived S3 upload policy, and the browser uploads image bytes directly to private S3 storage.

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
Presigned S3 POST
        |
        v
Private S3 bucket: incoming/
```

The image bytes do not pass through Lambda or API Gateway. The browser sends them directly to S3 using the presigned POST returned by the presign Lambda. S3 object keys use server-generated UUIDs; original filenames are never used as keys.

## Phase 3 upload support

- JPEG/JPG and PNG files
- Maximum size of 25 MiB
- Server-generated UUID object keys under the private `incoming/` prefix
- Client-side type and size checks, with backend and S3 policy validation authoritative

The frontend reads the API endpoint from `frontend/.env.local` using `VITE_UPLOAD_API_URL`. Use `frontend/.env.example` as the template. Local environment files are ignored by Git.

## Security controls

- Private S3 bucket with S3 Block Public Access enabled
- `BucketOwnerEnforced` object ownership
- SSE-S3 encryption using AES256
- TLS-only S3 bucket policy
- Presigned POST policies expire after 5 minutes
- POST policy enforces the upload size, `Content-Type`, generated key, and AES256 server-side encryption
- Lambda write access is restricted to `incoming/*`
- Original filenames are not used as S3 keys
- The frontend does not display or log signed AWS fields

## Cost controls and deliberate decisions

- Serverless, pay-per-use architecture
- HTTP API instead of the higher-cost REST API option
- No NAT Gateway
- No always-on compute
- No provisioned concurrency
- SSE-S3 instead of a customer-managed KMS key
- S3 lifecycle configuration deletes temporary objects after 30 days
- AWS Budget alerts provide cost visibility; they are not a hard spending cap, and AWS spending can exceed the alert threshold

## Current limitations

- API authorization is currently `NONE`, which is intentional for local/dev portfolio development
- API throttling reduces abuse risk but is not a hard quota, security boundary, or spending cap
- CORS currently allows only the local Vite origins (`http://localhost:5173` and `http://127.0.0.1:5173`)
- MIME metadata is not trusted as proof of real file content
- The processing pipeline is not deployed yet
- Terraform state is currently local
- The current direct `AdministratorAccess` bootstrap setup is temporary and is not the desired long-term deployment model

## Architectural decisions and tradeoffs

- HTTP API was selected over REST API for a lightweight upload endpoint.
- Presigned POST was selected instead of sending image bytes through Lambda, avoiding Lambda payload and execution costs for the upload itself.
- Presigned POST is used in part because its policy supports `content-length-range` enforcement.
- S3 versioning is intentionally disabled for disposable development image objects.
- `incoming/` is treated as an untrusted quarantine area.
- Cognito and WAF are not included yet because they are not justified for the current phase.
- Lambda is not placed in a VPC, so a NAT Gateway is not required.

## Testing completed

The current Phase 3 verification includes:

- Frontend production build passes
- 10 presign Lambda tests pass
- 4 existing image processor tests pass
- Real browser-to-API-to-S3 upload manually verified

Run the tests locally from the project root with the project virtual environment activated:

```bash
# Frontend
cd frontend
npm install
npm run build

# Python tests, from the project root
cd ..
python -m unittest discover -s lambda/tests -v
python -m unittest discover -s processor/tests -v
```

## Local image processor

The existing Pillow processor remains available locally while the AWS processing phase is being developed. Install its dependency in the project virtual environment:

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -r processor/requirements.txt
```

Process a local JPG or PNG:

```bash
python processor/process_image.py path/to/example.jpg
```

The processor writes thumbnail, medium, and optimized WebP outputs to `processor/output/`. It preserves aspect ratio, does not upscale, and composites PNG transparency onto white for JPEG outputs.

## Planned next architecture phase

Phase 4 is planned, not deployed:

```text
S3 incoming event
        |
        v
SQS
        |
        v
Processing Lambda using Pillow
        |
        v
Validated/transformed output
```

That phase should include SQS retries and a dead-letter queue, least-privilege IAM, and actual image signature/content validation rather than relying on MIME metadata alone. The project is not complete until that processing path is implemented, secured, and deployed.
