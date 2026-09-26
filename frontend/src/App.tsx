import { ChangeEvent, FormEvent, useEffect, useRef, useState } from 'react';

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const ACCEPTED_FILE_TYPES = ['image/jpeg', 'image/png'];
const POLL_INTERVAL_MS = 6_000;
const POLL_TIMEOUT_MS = 180_000;
const UPLOAD_ID_PATTERN = /^[0-9a-f]{32}$/;
const UPLOAD_API_URL = import.meta.env.VITE_UPLOAD_API_URL?.replace(/\/$/, '');

type UploadStatus = 'idle' | 'uploading' | 'processing' | 'complete' | 'error';

type ResultUrls = {
  thumbnail: string;
  medium: string;
  webp: string;
};

type PresignResponse = {
  upload_url: string;
  fields: Record<string, string>;
  upload_id: string;
};

type ProcessingResponse =
  | { status: 'processing' }
  | { status: 'complete'; outputs: ResultUrls };

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;

  const units = ['KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = -1;

  do {
    size /= 1024;
    unitIndex += 1;
  } while (size >= 1024 && unitIndex < units.length - 1);

  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parseProcessingResponse(value: unknown): ProcessingResponse | null {
  if (!isRecord(value) || (value.status !== 'processing' && value.status !== 'complete')) {
    return null;
  }

  if (value.status === 'processing') {
    return { status: 'processing' };
  }

  if (!isRecord(value.outputs)) {
    return null;
  }

  const { thumbnail, medium, webp } = value.outputs;
  if (
    typeof thumbnail !== 'string' ||
    !thumbnail.trim() ||
    typeof medium !== 'string' ||
    !medium.trim() ||
    typeof webp !== 'string' ||
    !webp.trim()
  ) {
    return null;
  }

  return { status: 'complete', outputs: { thumbnail, medium, webp } };
}

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [resultUrls, setResultUrls] = useState<ResultUrls | null>(null);
  const operationIdRef = useRef(0);
  const pollingAbortRef = useRef<AbortController | null>(null);
  const pollingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function cancelPolling() {
    operationIdRef.current += 1;
    pollingAbortRef.current?.abort();
    pollingAbortRef.current = null;

    if (pollingTimeoutRef.current !== null) {
      clearTimeout(pollingTimeoutRef.current);
      pollingTimeoutRef.current = null;
    }
  }

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(selectedFile);
    setPreviewUrl(objectUrl);

    return () => URL.revokeObjectURL(objectUrl);
  }, [selectedFile]);

  useEffect(() => {
    return () => cancelPolling();
  }, []);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    cancelPolling();
    setResultUrls(null);
    setStatusMessage(null);

    const file = event.target.files?.[0] ?? null;
    setStatus('idle');

    if (!file) {
      setSelectedFile(null);
      return;
    }

    if (!ACCEPTED_FILE_TYPES.includes(file.type)) {
      setSelectedFile(null);
      setStatus('error');
      setStatusMessage('Please choose a JPG or PNG image.');
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setSelectedFile(null);
      setStatus('error');
      setStatusMessage('Please choose an image no larger than 25 MiB.');
      return;
    }

    setSelectedFile(file);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedFile) {
      setStatus('error');
      setStatusMessage('Choose an image before uploading.');
      return;
    }

    if (!UPLOAD_API_URL) {
      setStatus('error');
      setStatusMessage('Upload is not configured. Set VITE_UPLOAD_API_URL and try again.');
      return;
    }

    cancelPolling();
    const operationId = operationIdRef.current;
    setResultUrls(null);
    setStatus('uploading');
    setStatusMessage('Preparing your upload…');

    try {
      const presignResponse = await fetch(`${UPLOAD_API_URL}/uploads/presign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: selectedFile.name,
          content_type: selectedFile.type,
          size_bytes: selectedFile.size,
        }),
      });

      if (!presignResponse.ok) {
        throw new Error('Unable to prepare the upload.');
      }

      const presignedPost = (await presignResponse.json()) as PresignResponse;
      if (
        !presignedPost.upload_url ||
        !presignedPost.fields ||
        typeof presignedPost.upload_id !== 'string' ||
        !UPLOAD_ID_PATTERN.test(presignedPost.upload_id)
      ) {
        throw new Error('The upload request was incomplete.');
      }

      const formData = new FormData();
      Object.entries(presignedPost.fields).forEach(([key, value]) => {
        formData.append(key, value);
      });
      formData.append('file', selectedFile);

      const uploadResponse = await fetch(presignedPost.upload_url, {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        throw new Error('The image upload was rejected.');
      }

      if (operationId !== operationIdRef.current) {
        return;
      }

      setStatus('processing');
      setStatusMessage('Upload complete. Processing your image…');
      startPolling(presignedPost.upload_id, operationId);
    } catch (error) {
      if (operationId !== operationIdRef.current) {
        return;
      }

      setStatus('error');
      setStatusMessage(error instanceof Error ? error.message : 'Unable to upload the image.');
    }
  }

  function startPolling(uploadId: string, operationId: number) {
    const startedAt = Date.now();

    const setPollingError = (message: string) => {
      if (operationId !== operationIdRef.current) {
        return;
      }

      setStatus('error');
      setStatusMessage(message);
    };

    const scheduleNextPoll = () => {
      if (operationId !== operationIdRef.current) {
        return;
      }

      const remainingMs = POLL_TIMEOUT_MS - (Date.now() - startedAt);
      if (remainingMs <= 0) {
        setPollingError('Processing is taking longer than expected. Please try again.');
        return;
      }

      pollingTimeoutRef.current = setTimeout(() => {
        pollingTimeoutRef.current = null;
        void poll();
      }, Math.min(POLL_INTERVAL_MS, remainingMs));
    };

    const poll = async () => {
      if (operationId !== operationIdRef.current) {
        return;
      }

      const remainingMs = POLL_TIMEOUT_MS - (Date.now() - startedAt);
      if (remainingMs <= 0) {
        setPollingError('Processing is taking longer than expected. Please try again.');
        return;
      }

      const controller = new AbortController();
      pollingAbortRef.current = controller;

      try {
        const response = await fetch(
          `${UPLOAD_API_URL}/uploads/${encodeURIComponent(uploadId)}/status`,
          { signal: controller.signal },
        );

        if (operationId !== operationIdRef.current) {
          return;
        }

        if (response.status === 429) {
          setStatusMessage('Processing is busy. We’ll check again shortly.');
          scheduleNextPoll();
          return;
        }

        if (!response.ok) {
          throw new Error('Unable to check processing status.');
        }

        let payload: unknown;
        try {
          payload = await response.json();
        } catch {
          throw new Error('The processing status response was invalid.');
        }

        const processingResponse = parseProcessingResponse(payload);
        if (!processingResponse) {
          throw new Error('The processing status response was invalid.');
        }

        if (processingResponse.status === 'processing') {
          setStatusMessage('Processing your image… We’ll check again shortly.');
          scheduleNextPoll();
          return;
        }

        setResultUrls(processingResponse.outputs);
        setStatus('complete');
        setStatusMessage('Your processed images are ready.');
      } catch (error) {
        if (controller.signal.aborted || operationId !== operationIdRef.current) {
          return;
        }

        setPollingError(error instanceof Error ? error.message : 'Unable to process the image.');
      } finally {
        if (pollingAbortRef.current === controller) {
          pollingAbortRef.current = null;
        }
      }
    };

    void poll();
  }

  const operationActive = status === 'uploading' || status === 'processing';

  return (
    <main className="page-shell">
      <section className="processing-card" aria-labelledby="page-title">
        <div className="eyebrow">Serverless image upload</div>
        <h1 id="page-title">AWS Serverless Image Processing Platform</h1>
        <p className="intro">
          Upload a JPG or PNG image to begin processing it through the serverless pipeline.
        </p>

        <form onSubmit={handleUpload}>
          <label className="file-picker">
            <span>Choose an image</span>
            <input
              type="file"
              accept=".jpg,.jpeg,.png,image/jpeg,image/png"
              onChange={handleFileChange}
              disabled={status === 'uploading'}
            />
          </label>
          {statusMessage && (
            <p
              className={`status-message status-${status}`}
              role={status === 'error' ? 'alert' : undefined}
              aria-live="polite"
              aria-atomic="true"
            >
              {statusMessage}
            </p>
          )}

          {selectedFile && previewUrl ? (
            <div className="image-details">
              <div className="preview-frame">
                <img src={previewUrl} alt={`Preview of ${selectedFile.name}`} />
              </div>
              <dl className="file-metadata">
                <div>
                  <dt>File name</dt>
                  <dd>{selectedFile.name}</dd>
                </div>
                <div>
                  <dt>Original file size</dt>
                  <dd>{formatFileSize(selectedFile.size)}</dd>
                </div>
              </dl>
            </div>
          ) : (
            <div className="empty-preview" aria-live="polite">
              <span className="empty-preview-icon" aria-hidden="true">+</span>
              <p>Your image preview will appear here.</p>
            </div>
          )}

          <button className="process-button" type="submit" disabled={!selectedFile || operationActive}>
            {status === 'uploading' ? 'Uploading…' : status === 'processing' ? 'Processing…' : 'Upload Image'}
          </button>
        </form>

        {status === 'complete' && resultUrls && (
          <section className="results-section" aria-labelledby="results-title">
            <div className="results-heading">
              <div>
                <div className="eyebrow">Ready to explore</div>
                <h2 id="results-title">Processed results</h2>
              </div>
              <span className="completion-badge">Complete</span>
            </div>

            <div className="results-grid">
              <article className="result-card">
                <div className="result-preview">
                  <img src={resultUrls.thumbnail} alt="Thumbnail processed result" />
                </div>
                <div className="result-card-content">
                  <h3>Thumbnail</h3>
                  <a href={resultUrls.thumbnail} target="_blank" rel="noreferrer">
                    Open result
                  </a>
                </div>
              </article>

              <article className="result-card">
                <div className="result-preview">
                  <img src={resultUrls.medium} alt="Medium processed result" />
                </div>
                <div className="result-card-content">
                  <h3>Medium</h3>
                  <a href={resultUrls.medium} target="_blank" rel="noreferrer">
                    Open result
                  </a>
                </div>
              </article>

              <article className="result-card">
                <div className="result-preview">
                  <img src={resultUrls.webp} alt="Optimized WebP processed result" />
                </div>
                <div className="result-card-content">
                  <h3>Optimized WebP</h3>
                  <a href={resultUrls.webp} target="_blank" rel="noreferrer">
                    Open result
                  </a>
                </div>
              </article>
            </div>
          </section>
        )}
      </section>
    </main>
  );
}

export default App;
