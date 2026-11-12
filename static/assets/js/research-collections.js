"use strict";

(() => {
  const panel = document.getElementById("collection-preparation");
  if (!panel || panel.dataset.autoPrepare !== "true") return;
  const continueLink = document.getElementById("collection-preparation-continue");
  const retryLink = document.getElementById("collection-preparation-retry");
  const message = document.getElementById("collection-preparation-message");
  const count = document.getElementById("collection-preparation-count");
  let active = true;
  let controller;
  let timer;
  let attempts = 0;
  let unchanged = 0;
  continueLink.hidden = true;

  function stop(text) {
    active = false;
    clearTimeout(timer);
    message.textContent = text;
    retryLink.hidden = false;
  }

  async function prepare() {
    if (!active) return;
    if (document.hidden) {
      timer = setTimeout(prepare, 1000);
      return;
    }
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(continueLink.href, {
        credentials: "same-origin", cache: "no-store", signal: controller.signal,
      });
      if (!active) return;
      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const next = page.getElementById("collection-preparation");
      if (response.redirected) throw new Error("The selection is no longer available.");
      if (!next) {
        if (response.status !== 200 || !page.querySelector(".collection-page #collection-title")) {
          throw new Error("The collection could not be opened.");
        }
        active = false;
        location.replace(continueLink.href);
        return;
      }
      if (![202, 503].includes(response.status)) throw new Error("Preparation could not continue.");
      const ready = Number(next.dataset.ready);
      const total = Number(next.dataset.total);
      if (!Number.isInteger(ready) || !Number.isInteger(total) || ready < 0 || total < ready) {
        throw new Error("Preparation status is unavailable.");
      }
      unchanged = ready > Number(panel.dataset.ready) ? 0 : unchanged + 1;
      panel.dataset.ready = String(ready);
      panel.dataset.total = String(total);
      count.textContent = `${ready} of ${total} objects ready`;
      if (next.dataset.requiresAdmin === "true") {
        stop("Some records need preparation by an administrator before this view can open.");
        return;
      }
      if (++attempts >= 1000 || unchanged >= 10) {
        stop("Preparation has paused. Retry to continue.");
        return;
      }
      timer = setTimeout(prepare, 500);
    } catch {
      if (active) stop("Preparation was interrupted. Retry to continue.");
    } finally {
      clearTimeout(timeout);
    }
  }

  window.addEventListener("pagehide", () => {
    active = false;
    clearTimeout(timer);
    controller?.abort();
  });
  window.addEventListener("pageshow", event => {
    if (event.persisted) stop("Preparation has paused. Retry to continue.");
  });
  timer = setTimeout(prepare, 500);
})();

(() => {
  const form = document.getElementById("collection-members-form");
  if (!form) return;
  const boxes = Array.from(form.querySelectorAll(".collection-member-checkbox"));
  const all = document.getElementById("collection-select-all");
  const count = document.getElementById("collection-selection-count");
  const remove = document.getElementById("collection-remove-button");
  document.getElementById("collection-select-all-label").hidden = false;
  count.hidden = false;

  function updateSelection() {
    const selected = boxes.filter(box => box.checked).length;
    count.textContent = `${selected} selected`;
    remove.disabled = selected === 0;
    all.checked = boxes.length > 0 && selected === boxes.length;
    all.indeterminate = selected > 0 && selected < boxes.length;
  }

  all.addEventListener("change", () => {
    boxes.forEach(box => { box.checked = all.checked; });
    updateSelection();
  });
  boxes.forEach(box => box.addEventListener("change", updateSelection));
  window.addEventListener("pageshow", updateSelection);
  updateSelection();
})();
