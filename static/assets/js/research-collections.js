"use strict";

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
