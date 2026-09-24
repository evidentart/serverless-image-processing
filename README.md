# AWS Serverless Image Processing Platform

A local foundation for a portfolio project that will eventually process images through AWS serverless services. This phase intentionally contains only a React frontend and a local Python/Pillow image processor.

## Project structure

```text
.
├── frontend/                 # React + TypeScript + Vite interface
└── processor/                # Local Python 3.12 + Pillow processor
    ├── output/               # Generated images (ignored by Git)
    ├── process_image.py      # Processing module and CLI entry point
    ├── requirements.txt
    └── tests/
```

## Run the frontend

Prerequisite: Node.js 18+ and npm.

From the project root:

```bash
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`. The page accepts JPG and PNG files, shows a local preview and file metadata, and keeps the **Process Image** button disabled until a later phase. No file is uploaded anywhere.

To create a production build locally:

```bash
npm run build
```

## Run the Python processor

Prerequisite: Python 3.12.

From the project root, create and activate a virtual environment, then install Pillow:

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

Alternatively, run the command from inside `processor/`:

```bash
cd processor
python process_image.py input/example.jpg
```

The processor writes these files to `processor/output/`:

```text
example_thumbnail.jpg    # maximum 200x200
example_medium.jpg       # maximum 800x800
example_optimized.webp  # optimized WebP version
```

The thumbnail and medium images are not upscaled and all generated images preserve the source aspect ratio. PNG transparency is composited onto white for the JPEG outputs.

## Run Python tests

From the project root:

```bash
python -m unittest discover -s processor/tests -v
```

The tests create temporary JPG and PNG images, verify the generated formats and dimensions, check aspect ratio preservation, and confirm that unsupported file types produce a readable error. They do not leave files in `processor/output/`.

## Scope

This phase does not include AWS infrastructure, Terraform, authentication, databases, queues, uploads, or deployment configuration.
