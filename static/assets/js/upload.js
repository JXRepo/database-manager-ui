document.addEventListener('DOMContentLoaded', function() {
  const form = document.getElementById('uploadForm');
  const input = document.getElementById('file-input');
  const box = document.querySelector('.file-upload-box');
  const fileInfo = document.getElementById('file-info');
  const fileText = document.getElementById('file-text');
  const removeBtn = document.getElementById('remove-file');
  const placeholder = document.getElementById('placeholder-text');
  const submitButton = document.getElementById('uploadButton');
  const submitLabel = document.getElementById('uploadButtonLabel');
  const status = document.getElementById('uploadStatus');
  const results = document.getElementById('upload-results');
  const maxFiles = 5;
  let dragHighlightTimer = null;
  let uploading = false;
  let selectionSubmitted = false;
  let requestId = 0;
  let requestController = null;
  let fileRows = [];

  removeBtn.textContent = 'x';

  function showDragHighlight() {
    if (uploading) return;
    if (dragHighlightTimer) {
      window.clearTimeout(dragHighlightTimer);
    }

    box.classList.add('drag-active');
  }

  function hideDragHighlightSoon() {
    if (dragHighlightTimer) {
      window.clearTimeout(dragHighlightTimer);
    }

    dragHighlightTimer = window.setTimeout(function() {
      box.classList.remove('drag-active');
    }, 80);
  }

  function resetFileSelection() {
    input.value = '';
    fileText.innerHTML = '';
    fileInfo.style.display = 'none';
    placeholder.style.display = 'block';
    removeBtn.style.display = 'none';
    box.classList.remove('active');
    fileRows = [];
    selectionSubmitted = false;
    submitButton.disabled = false;
    status.hidden = true;
    status.textContent = '';
  }

  function updateSelectedFiles(files) {
    selectionSubmitted = false;
    submitButton.disabled = false;
    status.hidden = true;
    status.textContent = '';
    if (files.length > maxFiles) {
      resetFileSelection();
      alert(`You can upload up to ${maxFiles} JSON files at once.`);
      return;
    }

    if (files.length > 0) {
      fileText.innerHTML = '';
      fileRows = [];
      files.forEach(function(file) {
        const row = document.createElement('span');
        row.className = 'selected-file-row';
        const fileName = document.createElement('span');
        fileName.className = 'selected-file-name';
        fileName.textContent = file.name;
        fileName.title = file.name;
        const progress = document.createElement('span');
        progress.className = 'selected-file-progress';
        const spinner = document.createElement('span');
        spinner.className = 'spinner-border spinner-border-sm selected-file-spinner';
        spinner.hidden = true;
        spinner.setAttribute('aria-hidden', 'true');
        const label = document.createElement('span');
        label.className = 'selected-file-status';
        label.textContent = 'Waiting';
        progress.append(spinner, label);
        row.append(fileName, progress);
        fileText.appendChild(row);
        fileRows.push({row, spinner, label, state: 'waiting'});
      });
      fileInfo.style.display = 'flex';
      placeholder.style.display = 'none';
      removeBtn.style.display = 'inline-flex';
      box.classList.add('active');
    } else {
      resetFileSelection();
    }
  }

  input.addEventListener('change', function(e) {
    if (uploading) return;
    updateSelectedFiles(Array.from(e.target.files));
  });

  function setUploading(active) {
    uploading = active;
    submitButton.disabled = active || selectionSubmitted;
    submitLabel.textContent = active ? 'Uploading…' : 'Upload';
    form.setAttribute('aria-busy', String(active));
    box.setAttribute('aria-disabled', String(active));
    removeBtn.style.display = active || !input.files.length ? 'none' : 'inline-flex';
    box.classList.remove('drag-active');
  }

  function showStatus(message) {
    status.textContent = message;
    status.hidden = false;
  }

  function setFileState(index, state, label) {
    const file = fileRows[index];
    file.state = state;
    file.row.dataset.state = state;
    file.label.textContent = label;
    file.spinner.hidden = state !== 'processing';
  }

  function showUnconfirmed() {
    fileRows.forEach(function(file, index) {
      if (file.state !== 'uploaded' && file.state !== 'failed') {
        setFileState(index, 'unconfirmed', 'Unconfirmed');
      }
    });
    showStatus('The upload result could not be confirmed. Check My Data before selecting files to upload again.');
  }

  function showRejected(message) {
    fileRows.forEach(function(file, index) {
      setFileState(index, 'rejected', 'Not uploaded');
    });
    showStatus(message);
  }

  function displayReport(event) {
    const alert = document.createElement('div');
    const level = event.level === 'error' ? 'danger' : event.level;
    alert.className = `alert alert-${level} mb-3`;
    const summary = document.createElement('p');
    summary.className = 'mb-0';
    summary.textContent = event.summary;
    alert.appendChild(summary);
    if (event.report_html) {
      const report = document.createElement('div');
      report.className = 'mt-3';
      // This HTML comes from the server template, which escapes uploaded text
      report.innerHTML = event.report_html;
      alert.appendChild(report);
    }
    results.replaceChildren(alert);
    showStatus('Finished. Select files again to start another upload.');
  }

  async function readProgress(response, currentRequest) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8', {fatal: true});
    let pending = '';
    let nextIndex = 0;
    let activeIndex = -1;
    let complete = null;

    function handleEvent(event) {
      if (!event || complete) throw new Error('Unexpected upload event');
      if (event.type === 'file_start') {
        if (activeIndex !== -1 || event.index !== nextIndex || nextIndex >= fileRows.length) {
          throw new Error('Unexpected file order');
        }
        activeIndex = event.index;
        setFileState(activeIndex, 'processing', 'Processing');
        showStatus(`Processing file ${activeIndex + 1} of ${fileRows.length}…`);
      } else if (event.type === 'file_result') {
        if (activeIndex < 0 || event.index !== activeIndex ||
            !['uploaded', 'failed'].includes(event.status) ||
            !Number.isInteger(event.saved_count) || event.saved_count < 0 ||
            (event.status === 'failed' && event.saved_count !== 0)) {
          throw new Error('Unexpected file result');
        }
        setFileState(activeIndex, event.status, event.status === 'uploaded' ? 'Uploaded' : 'Failed');
        activeIndex = -1;
        nextIndex += 1;
      } else if (event.type === 'complete') {
        if (activeIndex !== -1 || nextIndex !== fileRows.length ||
            typeof event.summary !== 'string' || typeof event.report_html !== 'string' ||
            !['success', 'warning', 'error'].includes(event.level)) {
          throw new Error('Incomplete upload results');
        }
        complete = event;
      } else {
        throw new Error('Unknown upload event');
      }
    }

    try {
      while (true) {
        const chunk = await reader.read();
        if (currentRequest !== requestId) return;
        pending += decoder.decode(chunk.value, {stream: !chunk.done});
        let end = pending.indexOf('\n');
        while (end !== -1) {
          const line = pending.slice(0, end).trim();
          pending = pending.slice(end + 1);
          if (line) handleEvent(JSON.parse(line));
          end = pending.indexOf('\n');
        }
        if (chunk.done) break;
      }
      if (pending.trim() || !complete) throw new Error('Truncated upload response');
      displayReport(complete);
    } finally {
      reader.cancel().catch(function() {});
      reader.releaseLock();
    }
  }

  async function uploadFiles(currentRequest) {
    requestController = new AbortController();
    try {
      const response = await fetch(form.action || window.location.href, {
        method: 'POST',
        body: new FormData(form),
        headers: {Accept: 'application/x-ndjson'},
        credentials: 'same-origin',
        signal: requestController.signal,
      });
      if (currentRequest !== requestId) return;
      if (response.redirected) {
        showRejected('Your session has expired. Sign in again, then select the files to upload.');
        return;
      }
      if (response.status === 403) {
        showRejected('The upload was not accepted. Reload this page and sign in again if needed.');
        return;
      }
      if (response.status === 429) {
        showRejected('Too many upload attempts. Please wait before selecting files to try again.');
        return;
      }
      if (response.status === 503) {
        showUnconfirmed();
        showStatus('Uploading is temporarily unavailable. Check My Data before selecting files to upload again.');
        return;
      }
      const contentType = response.headers.get('Content-Type') || '';
      if (response.status === 400 && contentType.includes('application/json')) {
        const error = await response.json();
        if (currentRequest !== requestId) return;
        showRejected(typeof error.error === 'string' ? error.error : 'The upload was not accepted. Check your files and try again.');
        return;
      }
      if (!response.ok || !contentType.includes('application/x-ndjson') || !response.body) {
        throw new Error('Unexpected upload response');
      }
      await readProgress(response, currentRequest);
    } catch (error) {
      if (currentRequest === requestId) showUnconfirmed();
    } finally {
      if (currentRequest === requestId) {
        requestController = null;
        setUploading(false);
      }
    }
  }

  form.addEventListener('submit', function(e) {
    if (uploading || selectionSubmitted) {
      e.preventDefault();
      return;
    }
    if (!input.files.length) {
      e.preventDefault();
      status.textContent = 'Choose at least one JSON file to upload.';
      status.hidden = false;
      return;
    }
    if (input.files.length > maxFiles) {
      e.preventDefault();
      updateSelectedFiles(Array.from(input.files));
      return;
    }
    selectionSubmitted = true;
    results.replaceChildren();
    setUploading(true);
    const supportsStreaming = typeof fetch === 'function' && typeof ReadableStream === 'function' &&
      typeof TextDecoder === 'function' && typeof AbortController === 'function' &&
      typeof Response === 'function' && 'body' in Response.prototype;
    if (!supportsStreaming) {
      showStatus('Uploading and checking files…');
      return;
    }
    e.preventDefault();
    showStatus('Sending files…');
    uploadFiles(++requestId);
  });

  box.addEventListener('click', function(e) {
    if (uploading) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  window.addEventListener('pageshow', function(e) {
    if (e.persisted && uploading) {
      requestId += 1;
      if (requestController) requestController.abort();
      requestController = null;
      showUnconfirmed();
      setUploading(false);
    } else if (!selectionSubmitted) {
      setUploading(false);
      updateSelectedFiles(Array.from(input.files));
    }
  });

  function handlePageDrag(e) {
    e.preventDefault();
    e.stopPropagation();
    showDragHighlight();
  }

  function handlePageDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    hideDragHighlightSoon();
  }

  function handlePageDragEnd(e) {
    e.preventDefault();
    e.stopPropagation();
    box.classList.remove('drag-active');
  }

  window.addEventListener('dragenter', handlePageDrag, true);
  window.addEventListener('dragover', handlePageDrag, true);
  window.addEventListener('dragleave', handlePageDragLeave, true);
  window.addEventListener('dragend', handlePageDragEnd, true);

  box.addEventListener('drop', function(e) {
    e.preventDefault();
    e.stopPropagation();
    box.classList.remove('drag-active');
    if (uploading) return;

    const files = Array.from(e.dataTransfer.files).filter(function(file) {
      return file.name.toLowerCase().endsWith('.json');
    });

    if (!files.length) {
      resetFileSelection();
      alert('Please drop JSON files only.');
      return;
    }

    const transfer = new DataTransfer();
    files.forEach(function(file) {
      transfer.items.add(file);
    });
    input.files = transfer.files;
    updateSelectedFiles(files);
  });

  removeBtn.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    if (uploading) return;
    resetFileSelection();
  });
});
