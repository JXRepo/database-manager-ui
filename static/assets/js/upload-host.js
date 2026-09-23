(() => {
  'use strict';

  const configuration = document.currentScript;
  const jobsUrl = configuration?.dataset.jobsUrl;
  const uploadUrl = configuration?.dataset.uploadUrl || '/upload/';
  const userId = configuration?.dataset.userId || '';
  if (!jobsUrl || typeof fetch !== 'function' || typeof window.crypto?.getRandomValues !== 'function') return;

  function isApplicationUrl(url) {
    return url.origin === location.origin && (
      ['/', '/search/', '/data-list/', '/share/', '/shared-with-me/', '/sharing-history/',
        '/charts/', '/notifications/', '/settings/', uploadUrl].includes(url.pathname) ||
      /^\/data-list\/\d+\/(sharing\/)?$/.test(url.pathname) ||
      /^\/notifications\/\d+\/open\/$/.test(url.pathname)
    );
  }

  function attachNavigation(host) {
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
          event.shiftKey || event.altKey || link.hasAttribute('download') ||
          (link.target && link.target !== '_self')) return;
      if (link.getAttribute('href').startsWith('#')) return;
      const url = new URL(link.href, location.href);
      if (url.pathname === location.pathname && url.search === location.search && url.hash) return;
      if (/\/export(?:-selected)?\/$/.test(url.pathname)) return;
      if (isApplicationUrl(url) && host.isHosting()) {
        event.preventDefault();
        host.navigate(url.href);
      } else if (window !== window.top && !isApplicationUrl(url) && !link.href.startsWith('#')) {
        link.target = '_top';
      }
    });
    document.addEventListener('submit', event => {
      const form = event.target;
      if (event.defaultPrevented || form.id === 'uploadForm') return;
      const action = new URL(event.submitter?.getAttribute('formaction') || form.action || location.href, location.href);
      if (!isApplicationUrl(action)) {
        if (window !== window.top && !/\/export(?:-selected)?\/$/.test(action.pathname)) form.target = '_top';
        return;
      }
      if ((form.method || 'get').toLowerCase() !== 'get' || !host.isHosting()) return;
      event.preventDefault();
      const data = new FormData(form);
      if (event.submitter?.name) data.append(event.submitter.name, event.submitter.value);
      action.search = new URLSearchParams(data).toString();
      host.navigate(action.href);
    });
  }

  if (window.parent !== window) {
    try {
      const parentHost = window.parent.FairUploadHost;
      if (parentHost && window.frameElement?.id === 'upload-page-frame') {
        if (userId && parentHost.userId && userId !== parentHost.userId) {
          parentHost.leaveForAccount(location.href);
          return;
        }
        window.FairUploadHost = parentHost;
        attachNavigation(parentHost);
        return;
      }
    } catch (_) {
      return;
    }
  }
  if (window.FairUploadHost) return;

  const listeners = new Set();
  const state = {active: false, transferring: false, job: null, message: '', loaded: 0, total: 0};
  let frame = null;
  let banner = null;
  let pollTimer = null;
  let generation = 0;
  let returnUrl = new URL(uploadUrl, location.href).href;
  let frameUrl = '';
  let coveredElements = [];
  const initialTitle = document.title;
  const terminalStates = ['completed', 'interrupted', 'rejected'];

  function leaveForAccount(url) {
    generation += 1;
    clearTimeout(pollTimer);
    Object.assign(state, {active: false, transferring: false, job: null,
      message: 'Sign in again to check your upload result.', authExpired: true});
    emit();
    location.assign(url);
  }

  function jobMessage(job) {
    if (terminalStates.includes(job.status)) return job.summary || 'Upload finished. Open upload details.';
    const file = job.files.find(item => ['parsing', 'validating', 'saving'].includes(item.status));
    if (file?.status === 'validating') {
      return `Validating ${file.name}: ${file.validated_count} of ${file.object_count ?? '?'} objects checked`;
    }
    if (file?.status === 'saving') return `Saving ${file.name}…`;
    if (file) return `Reading ${file.name}…`;
    return 'Files received. Waiting to process…';
  }

  function ensureBanner() {
    if (banner) return;
    banner = document.createElement('aside');
    banner.id = 'upload-global-status';
    banner.setAttribute('aria-label', 'Upload progress');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2000;min-height:44px;padding:10px 20px;background:#f0f7ff;border-bottom:1px solid #cbdcf0;color:#253954;display:flex;align-items:center;justify-content:space-between;gap:16px;font:14px/1.5 system-ui';
    const message = document.createElement('span');
    message.setAttribute('role', 'status');
    message.style.overflowWrap = 'anywhere';
    const details = document.createElement('a');
    details.href = uploadUrl;
    details.textContent = 'Upload details';
    details.style.cssText = 'white-space:nowrap;color:#1757a3';
    banner.append(message, details);
    document.body.appendChild(banner);
  }

  function emit() {
    if (state.message) ensureBanner();
    if (banner) {
      banner.firstElementChild.textContent = state.message;
      banner.hidden = !state.message || (!frame && !!document.getElementById('uploadForm'));
      banner.style.display = banner.hidden ? 'none' : 'flex';
      if (frame) {
        const height = banner.getBoundingClientRect().height;
        frame.style.top = `${height}px`;
        frame.style.height = `calc(100% - ${height}px)`;
      }
    }
    for (const listener of listeners) listener({...state});
  }

  function restoreUpload(push = true) {
    frame?.remove();
    frame = null;
    frameUrl = '';
    coveredElements.forEach(({element, inert}) => { element.inert = inert; });
    coveredElements = [];
    document.documentElement.style.overflow = '';
    document.title = initialTitle;
    if (push) history.pushState({uploadHost: true, url: returnUrl}, '', returnUrl);
    emit();
  }

  function navigate(url, push = true) {
    const target = new URL(url, location.href);
    if (!isApplicationUrl(target)) {
      location.assign(target.href);
      return;
    }
    if (target.pathname === new URL(uploadUrl, location.href).pathname) {
      if (document.getElementById('uploadForm')) restoreUpload(push);
      else location.assign(target.href);
      return;
    }
    if (!state.transferring && !frame) {
      location.assign(target.href);
      return;
    }
    if (!frame) {
      history.replaceState({uploadHost: true, url: location.href}, '', location.href);
      frame = document.createElement('iframe');
      frame.id = 'upload-page-frame';
      frame.title = 'Application page';
      frame.style.cssText = 'position:fixed;inset:44px 0 0;width:100%;height:calc(100% - 44px);border:0;background:white;z-index:1900';
      frame.addEventListener('load', () => {
        try {
          const currentUrl = frame.contentWindow.location.href;
          if (currentUrl === 'about:blank') return;
          if (!isApplicationUrl(new URL(currentUrl))) {
            location.assign(currentUrl);
            return;
          }
          frameUrl = currentUrl;
          history.replaceState({uploadHost: true, url: currentUrl}, '', currentUrl);
          document.title = frame.contentDocument.title;
        } catch (_) {
          state.message = 'This page could not open here. Return to upload details before continuing.';
          emit();
        }
      });
      ensureBanner();
      coveredElements = Array.from(document.body.children)
        .filter(element => element !== banner && !['SCRIPT', 'STYLE'].includes(element.tagName))
        .map(element => ({element, inert: element.inert}));
      coveredElements.forEach(({element}) => { element.inert = true; });
      document.body.appendChild(frame);
      document.documentElement.style.overflow = 'hidden';
    }
    if (push) history.pushState({uploadHost: true, url: target.href}, '', target.href);
    frameUrl = target.href;
    frame.contentWindow.location.replace(target.href);
    emit();
  }

  function accept(job) {
    if (!job || typeof job.id !== 'string' || !Array.isArray(job.files)) throw new Error('Invalid upload task');
    state.job = job;
    state.transferring = false;
    state.active = !terminalStates.includes(job.status);
    state.message = jobMessage(job);
    emit();
    clearTimeout(pollTimer);
    if (state.active) pollTimer = setTimeout(() => refresh(false), 1000);
  }

  async function refresh(latest = true) {
    const currentGeneration = generation;
    const target = latest || !state.job ? jobsUrl : `${jobsUrl}${encodeURIComponent(state.job.id)}/`;
    try {
      const response = await fetch(target, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
      if (currentGeneration !== generation || state.transferring) return;
      if (response.status === 401 || response.status === 403 || response.redirected) {
        leaveForAccount(`/login/?next=${encodeURIComponent(uploadUrl)}`);
        return;
      }
      if (!response.ok) throw new Error('Upload status unavailable');
      const result = await response.json();
      if (currentGeneration !== generation || state.transferring) return;
      if (result.job) accept(result.job);
    } catch (_) {
      if (currentGeneration !== generation || state.transferring || !state.job) return;
      state.message = 'Upload status is temporarily unavailable. Checking again…';
      emit();
      pollTimer = setTimeout(() => refresh(false), 3000);
    }
  }

  window.FairUploadHost = {
    jobsUrl,
    userId,
    leaveForAccount,
    getState: () => ({...state}),
    isHosting: () => state.transferring || !!frame,
    navigate,
    subscribe(listener) {
      listeners.add(listener);
      listener({...state});
      return () => listeners.delete(listener);
    },
    resume() {
      clearTimeout(pollTimer);
      refresh(!state.job);
    },
    start() {
      if (state.active) return false;
      generation += 1;
      clearTimeout(pollTimer);
      returnUrl = location.href;
      Object.assign(state, {active: true, transferring: true, job: null, message: 'Sending files…', loaded: 0, total: 0});
      emit();
      return true;
    },
    progress(loaded, total) {
      state.loaded = loaded;
      state.total = total;
      const divisor = total >= 1024 * 1024 ? 1024 * 1024 : 1024;
      const unit = divisor === 1024 ? 'KiB' : 'MiB';
      state.message = total
        ? `Sending submission: ${Math.min(100, Math.floor(loaded / total * 100))}% · ${(loaded / divisor).toFixed(1)} / ${(total / divisor).toFixed(1)} ${unit}`
        : `Sending submission: ${loaded.toLocaleString()} bytes sent`;
      emit();
    },
    received() {
      state.message = 'Files sent. Waiting for server confirmation…';
      emit();
    },
    accept,
    fail(message) {
      state.active = false;
      state.transferring = false;
      state.message = message;
      emit();
    },
  };

  attachNavigation(window.FairUploadHost);
  window.addEventListener('popstate', event => {
    if (!frame && !event.state?.uploadHost) return;
    const target = event.state?.url || location.href;
    if (target !== frameUrl) navigate(target, false);
  });
  window.addEventListener('beforeunload', event => {
    if (!state.transferring) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('resize', emit);
  refresh();
})();
