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
  const spinner = document.getElementById('uploadSpinner');
  const status = document.getElementById('uploadStatus');
  const maxFiles = 5;
  let dragHighlightTimer = null;
  let uploading = false;

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
  }

  function updateSelectedFiles(files) {
    status.hidden = true;
    status.textContent = '';
    if (files.length > maxFiles) {
      resetFileSelection();
      alert(`You can upload up to ${maxFiles} JSON files at once.`);
      return;
    }

    if (files.length > 0) {
      fileText.innerHTML = '';
      files.forEach(function(file) {
        const fileName = document.createElement('span');
        fileName.className = 'selected-file-name';
        fileName.textContent = file.name;
        fileText.appendChild(fileName);
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
    submitButton.disabled = active;
    submitLabel.textContent = active ? 'Uploading…' : 'Upload';
    spinner.hidden = !active;
    status.hidden = !active;
    status.textContent = active ? 'Uploading and checking files…' : '';
    form.setAttribute('aria-busy', String(active));
    box.setAttribute('aria-disabled', String(active));
    removeBtn.style.display = active || !input.files.length ? 'none' : 'inline-flex';
    box.classList.remove('drag-active');
  }

  form.addEventListener('submit', function(e) {
    if (uploading) {
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
    setUploading(true);
  });

  box.addEventListener('click', function(e) {
    if (uploading) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  window.addEventListener('pageshow', function() {
    setUploading(false);
    updateSelectedFiles(Array.from(input.files));
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
