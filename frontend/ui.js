/** Shared UI: loading buttons, panel transitions, staggered reveals. */
(() => {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function busy(button, on, busyLabel) {
    if (!button) return;
    if (on) {
      if (!button.dataset.uiIdleLabel) button.dataset.uiIdleLabel = button.textContent.trim();
      button.classList.add("is-busy");
      button.disabled = true;
      if (busyLabel) button.textContent = busyLabel;
    } else {
      button.classList.remove("is-busy");
      button.disabled = false;
      if (button.dataset.uiIdleLabel) button.textContent = button.dataset.uiIdleLabel;
    }
  }

  function reveal(root, selector = ".ui-stagger > *, .sig, .sec-row, .bubble, .bp-card") {
    if (!root || reduced) return;
    const nodes = root.matches?.(selector) ? [root] : [...root.querySelectorAll(selector)];
    nodes.forEach((el, i) => {
      el.classList.remove("ui-in");
      void el.offsetWidth;
      el.style.setProperty("--ui-delay", `${Math.min(i * 45, 400)}ms`);
      el.classList.add("ui-in");
    });
  }

  function showBpView(showEl, hideEls) {
    (hideEls || []).forEach((el) => {
      if (!el || el === showEl) return;
      el.classList.remove("bp-view-visible");
      el.hidden = true;
    });
    if (!showEl) return;
    showEl.hidden = false;
    requestAnimationFrame(() => showEl.classList.add("bp-view-visible"));
  }

  window.UI = { busy, reveal, showBpView, reduced };
})();
