// HydroModPy: lightweight before/after image comparison slider.
// Markup expected: a container with class "hmp-image-compare" containing
// two child elements with classes "hmp-before" and "hmp-after". Both are
// stacked; the "after" image is clipped left-of-handle and revealed by
// dragging the handle.
(function () {
  function clamp(value, lo, hi) {
    return Math.max(lo, Math.min(hi, value));
  }

  function init(container) {
    if (container.dataset.hmpInitialised === "1") {
      return;
    }
    container.dataset.hmpInitialised = "1";
    const before = container.querySelector(".hmp-before");
    const after = container.querySelector(".hmp-after");
    if (!before || !after) {
      return;
    }
    const handle = document.createElement("div");
    handle.className = "hmp-image-compare-handle";
    handle.setAttribute("role", "slider");
    handle.setAttribute("aria-label", "Drag to compare images");
    handle.setAttribute("aria-valuemin", "0");
    handle.setAttribute("aria-valuemax", "100");
    handle.setAttribute("aria-valuenow", "50");
    handle.tabIndex = 0;
    container.appendChild(handle);

    function update(positionRatio) {
      const ratio = clamp(positionRatio, 0, 1);
      handle.style.left = `${ratio * 100}%`;
      after.style.clipPath = `inset(0 0 0 ${ratio * 100}%)`;
      handle.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    }

    function pointerToRatio(clientX) {
      const rect = container.getBoundingClientRect();
      return (clientX - rect.left) / rect.width;
    }

    let dragging = false;
    function startDrag(clientX) {
      dragging = true;
      update(pointerToRatio(clientX));
    }
    function moveDrag(clientX) {
      if (!dragging) return;
      update(pointerToRatio(clientX));
    }
    function endDrag() {
      dragging = false;
    }

    container.addEventListener("mousedown", (event) => startDrag(event.clientX));
    document.addEventListener("mousemove", (event) => moveDrag(event.clientX));
    document.addEventListener("mouseup", endDrag);

    container.addEventListener(
      "touchstart",
      (event) => {
        if (event.touches.length) startDrag(event.touches[0].clientX);
      },
      { passive: true }
    );
    document.addEventListener(
      "touchmove",
      (event) => {
        if (event.touches.length) moveDrag(event.touches[0].clientX);
      },
      { passive: true }
    );
    document.addEventListener("touchend", endDrag);

    handle.addEventListener("keydown", (event) => {
      const step = event.shiftKey ? 0.1 : 0.02;
      const current = parseFloat(handle.getAttribute("aria-valuenow")) / 100;
      if (event.key === "ArrowLeft") {
        update(current - step);
        event.preventDefault();
      } else if (event.key === "ArrowRight") {
        update(current + step);
        event.preventDefault();
      } else if (event.key === "Home") {
        update(0);
        event.preventDefault();
      } else if (event.key === "End") {
        update(1);
        event.preventDefault();
      }
    });

    update(0.5);
  }

  function bootstrap() {
    document.querySelectorAll(".hmp-image-compare").forEach(init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }
})();
