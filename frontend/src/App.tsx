import { ChangeEvent, useEffect, useState } from 'react';

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const ACCEPTED_FILE_TYPES = ['image/jpeg', 'image/png'];

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
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

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
    setValidationMessage(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    if (!ACCEPTED_FILE_TYPES.includes(file.type)) {
      setSelectedFile(null);
      setValidationMessage('Please choose a JPG or PNG image.');
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setSelectedFile(null);
      setValidationMessage('Please choose an image smaller than 25 MB.');
      return;
    }

    setSelectedFile(file);
  }

  return (
    <main className="page-shell">
      <section className="processing-card" aria-labelledby="page-title">
        <div className="eyebrow">Local project foundation</div>
        <h1 id="page-title">AWS Serverless Image Processing Platform</h1>
        <p className="intro">
          Select a JPG or PNG image to preview it. Processing will be connected in a later phase.
        </p>

        <label className="file-picker">
          <span>Choose an image</span>
          <input type="file" accept="image/jpeg,image/png" onChange={handleFileChange} />
        </label>
        {validationMessage && <p className="validation-message" role="alert">{validationMessage}</p>}

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
            <span className="empty-preview-icon" aria-hidden="true">＋</span>
            <p>Your image preview will appear here.</p>
          </div>
        )}

        <button className="process-button" type="button" disabled>
          Process Image
        </button>
        <p className="coming-soon">Image processing is coming in a future phase.</p>
      </section>
    </main>
  );
}

export default App;
