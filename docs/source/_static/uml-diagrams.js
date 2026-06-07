(function () {
  function getDiagramSource(node) {
    const objectEl = node.querySelector("object[data]");
    if (objectEl && objectEl.getAttribute("data")) {
      return objectEl.getAttribute("data");
    }
    const imgEl = node.querySelector("img[src]");
    if (imgEl && imgEl.getAttribute("src")) {
      return imgEl.getAttribute("src");
    }
    return null;
  }

  function getDiagramNodes() {
    return Array.from(document.querySelectorAll(".bd-article .plantuml")).filter(function (node) {
      return !node.dataset.umlEnhanced && getDiagramSource(node);
    });
  }

  function getDiagramTitle(node, index) {
    const figure = node.closest("figure");
    if (figure) {
      const caption = figure.querySelector("figcaption");
      if (caption) {
        const label = caption.textContent.replace("#", "").trim();
        if (label) {
          return label;
        }
      }
    }

    const section = node.closest("section");
    if (section) {
      const heading = section.querySelector("h1, h2, h3, h4");
      if (heading) {
        const label = heading.textContent.replace("#", "").trim();
        if (label) {
          return label;
        }
      }
    }
    return "UML diagram " + (index + 1);
  }

  function createModal() {
    const modal = document.createElement("div");
    modal.className = "uml-modal";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="uml-modal__header">' +
      '  <div class="uml-modal__title"></div>' +
      '  <div class="uml-modal__actions">' +
      '    <a class="uml-modal__link" target="_blank" rel="noopener">Open in new tab</a>' +
      '    <button type="button" class="uml-modal__close">Close</button>' +
      "  </div>" +
      "</div>" +
      '<div class="uml-modal__stage">' +
      '  <figure class="uml-modal__figure">' +
      '    <img class="uml-modal__image" alt="Expanded UML diagram" />' +
      "  </figure>" +
      "</div>";

    const closeButton = modal.querySelector(".uml-modal__close");
    closeButton.addEventListener("click", function () {
      closeModal(modal);
    });

    modal.addEventListener("click", function (event) {
      if (event.target === modal || event.target === modal.querySelector(".uml-modal__stage")) {
        closeModal(modal);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !modal.hidden) {
        closeModal(modal);
      }
    });

    document.body.appendChild(modal);
    return modal;
  }

  function openModal(modal, src, title) {
    modal.querySelector(".uml-modal__title").textContent = title;
    modal.querySelector(".uml-modal__image").src = src;
    modal.querySelector(".uml-modal__link").href = src;
    modal.hidden = false;
    document.body.classList.add("uml-modal-open");
  }

  function closeModal(modal) {
    modal.hidden = true;
    document.body.classList.remove("uml-modal-open");
  }

  function enhancePlantUml(node, index, modal) {
    node.dataset.umlEnhanced = "true";

    const source = getDiagramSource(node);
    if (!source) {
      return;
    }

    const title = getDiagramTitle(node, index);
    const container = document.createElement("div");
    container.className = "uml-diagram";

    const toolbar = document.createElement("div");
    toolbar.className = "uml-diagram__toolbar";
    toolbar.innerHTML =
      '<div class="uml-diagram__meta">' +
      '  <span class="uml-diagram__badge">UML</span>' +
      '  <span class="uml-diagram__title"></span>' +
      '  <span class="uml-diagram__hint">Scroll to inspect, click to enlarge.</span>' +
      "</div>" +
      '<div class="uml-diagram__actions">' +
      '  <a class="uml-diagram__link" target="_blank" rel="noopener">Open full size</a>' +
      '  <button type="button" class="uml-diagram__button">Expand</button>' +
      "</div>";
    toolbar.querySelector(".uml-diagram__title").textContent = title;
    toolbar.querySelector(".uml-diagram__link").href = source;

    const viewport = document.createElement("button");
    viewport.type = "button";
    viewport.className = "uml-diagram__viewport";
    viewport.setAttribute("aria-label", "Open " + title + " in expanded view");
    viewport.setAttribute("aria-haspopup", "dialog");
    viewport.title = "Open full-size UML diagram";

    const image = document.createElement("img");
    image.className = "uml-diagram__image";
    image.src = source;
    image.alt = title;
    image.loading = "lazy";
    viewport.appendChild(image);

    toolbar.querySelector(".uml-diagram__button").addEventListener("click", function () {
      openModal(modal, source, title);
    });
    viewport.addEventListener("click", function () {
      openModal(modal, source, title);
    });

    container.appendChild(toolbar);
    container.appendChild(viewport);
    node.replaceWith(container);
  }

  function enhancePlantUmlDiagrams() {
    const diagrams = getDiagramNodes();
    if (!diagrams.length) {
      return;
    }

    const modal = document.querySelector(".uml-modal") || createModal();
    diagrams.forEach(function (node, index) {
      enhancePlantUml(node, index, modal);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    enhancePlantUmlDiagrams();
  });
})();
