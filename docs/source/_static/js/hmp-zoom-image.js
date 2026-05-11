/* Lightbox with pan + zoom for ER diagrams (and any img.hmp-zoomable). */
(function () {
    "use strict";

    function buildOverlay() {
        const overlay = document.createElement("div");
        overlay.className = "hmp-zoom-overlay";
        overlay.setAttribute("role", "dialog");
        overlay.setAttribute("aria-modal", "true");
        overlay.innerHTML =
            '<button type="button" class="hmp-zoom-close" aria-label="Close">x</button>' +
            '<div class="hmp-zoom-toolbar">' +
            '  <button type="button" data-act="out" aria-label="Zoom out">-</button>' +
            '  <button type="button" data-act="reset" aria-label="Reset view">100%</button>' +
            '  <button type="button" data-act="in" aria-label="Zoom in">+</button>' +
            '</div>' +
            '<div class="hmp-zoom-stage">' +
            '  <img alt="" />' +
            '</div>';
        document.body.appendChild(overlay);
        return overlay;
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function open(src, alt) {
        const overlay = document.querySelector(".hmp-zoom-overlay") || buildOverlay();
        const stage = overlay.querySelector(".hmp-zoom-stage");
        const img = overlay.querySelector("img");
        const closeBtn = overlay.querySelector(".hmp-zoom-close");

        let scale = 1;
        let tx = 0;
        let ty = 0;
        let dragging = false;
        let lastX = 0;
        let lastY = 0;

        img.src = src;
        img.alt = alt || "";

        function apply() {
            img.style.transform =
                "translate(" + tx + "px," + ty + "px) scale(" + scale + ")";
        }

        function reset() {
            scale = 1;
            tx = 0;
            ty = 0;
            apply();
        }

        function onWheel(e) {
            e.preventDefault();
            const rect = stage.getBoundingClientRect();
            const cx = e.clientX - rect.left - rect.width / 2;
            const cy = e.clientY - rect.top - rect.height / 2;
            const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
            const newScale = clamp(scale * factor, 0.2, 12);
            const ratio = newScale / scale;
            tx = cx - (cx - tx) * ratio;
            ty = cy - (cy - ty) * ratio;
            scale = newScale;
            apply();
        }

        function onMouseDown(e) {
            dragging = true;
            lastX = e.clientX;
            lastY = e.clientY;
            overlay.classList.add("dragging");
            e.preventDefault();
        }

        function onMouseMove(e) {
            if (!dragging) return;
            tx += e.clientX - lastX;
            ty += e.clientY - lastY;
            lastX = e.clientX;
            lastY = e.clientY;
            apply();
        }

        function onMouseUp() {
            dragging = false;
            overlay.classList.remove("dragging");
        }

        function onToolbar(e) {
            const act = e.target.getAttribute("data-act");
            if (!act) return;
            if (act === "in") {
                scale = clamp(scale * 1.25, 0.2, 12);
            } else if (act === "out") {
                scale = clamp(scale / 1.25, 0.2, 12);
            } else if (act === "reset") {
                reset();
                return;
            }
            apply();
        }

        function close() {
            overlay.classList.remove("open");
            stage.removeEventListener("wheel", onWheel);
            stage.removeEventListener("mousedown", onMouseDown);
            window.removeEventListener("mousemove", onMouseMove);
            window.removeEventListener("mouseup", onMouseUp);
            overlay.removeEventListener("keydown", onKey);
            overlay.removeEventListener("click", onOverlayClick);
            closeBtn.removeEventListener("click", close);
            overlay.querySelector(".hmp-zoom-toolbar").removeEventListener("click", onToolbar);
            document.body.classList.remove("hmp-zoom-open");
        }

        function onKey(e) {
            if (e.key === "Escape") close();
            if (e.key === "+" || e.key === "=") {
                scale = clamp(scale * 1.25, 0.2, 12);
                apply();
            }
            if (e.key === "-") {
                scale = clamp(scale / 1.25, 0.2, 12);
                apply();
            }
            if (e.key === "0") reset();
        }

        function onOverlayClick(e) {
            if (e.target === overlay) close();
        }

        reset();
        overlay.classList.add("open");
        document.body.classList.add("hmp-zoom-open");
        stage.addEventListener("wheel", onWheel, { passive: false });
        stage.addEventListener("mousedown", onMouseDown);
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
        overlay.addEventListener("click", onOverlayClick);
        closeBtn.addEventListener("click", close);
        overlay.querySelector(".hmp-zoom-toolbar").addEventListener("click", onToolbar);
        overlay.tabIndex = -1;
        overlay.focus();
        overlay.addEventListener("keydown", onKey);
    }

    function init() {
        const targets = document.querySelectorAll("img.hmp-zoomable");
        targets.forEach(function (img) {
            const link = img.closest("a");
            const trigger = link || img;
            trigger.classList.add("hmp-zoom-trigger");
            if (link) {
                link.setAttribute("href", img.src);
                link.setAttribute("target", "_blank");
                link.setAttribute("rel", "noopener");
            }
            trigger.addEventListener("click", function (e) {
                e.preventDefault();
                open(img.src, img.alt);
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
