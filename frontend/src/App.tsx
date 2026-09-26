import { ChangeEvent, FormEvent, useEffect, useState } from 'react';

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const ACCEPTED_FILE_TYPES = ['image/jpeg', 'image/png'];
const UPLOAD_API_URL = import.meta.env.VITE_UPLOAD_API_URL?.replace(/\/$/, '');

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';

type PresignResponse = {
  upload_url: string;
  fields: Record<string, string>;
};

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

function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<UploadStatus>('idle');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null);
      return;
    }

    const objectUrl = URL.createObjectURL(selectedFile);
    setPreviewUrl(objectUrl);

    return () => URL.revokeObjectURL(objectUrl);
  }, [selectedFile]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setStatus('idle');
    setStatusMessage(null);

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

    setStatus('uploading');
    setStatusMessage(null);

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
      if (!presignedPost.upload_url || !presignedPost.fields) {
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

      setStatus('success');
      setStatusMessage('Image uploaded successfully.');
    } catch (error) {
      setStatus('error');
      setStatusMessage(error instanceof Error ? error.message : 'Unable to upload the image.');
    }
  }

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
            <p className={`status-message status-${status}`} role={status === 'error' ? 'alert' : 'status'}>
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

          <button className="process-button" type="submit" disabled={!selectedFile || status === 'uploading'}>
            {status === 'uploading' ? 'Uploading…' : 'Upload Image'}
          </button>
        </form>
      </section>
    </main>
  );
}

export default App;
