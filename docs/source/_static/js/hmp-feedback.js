// HydroModPy: "Was this page helpful?" widget.
// The widget appears once per page near the end of the main article. When
// the GoatCounter script is loaded (HMP_DOCS_GOATCOUNTER_URL is set at
// build time), clicks are pushed as ``feedback_yes`` or ``feedback_no``
// events. Otherwise the widget still renders and acknowledges the click,
// but no analytics call is made.
(function () {
  function isAnalyticsReady() {
    return typeof window !== "undefined" && typeof window.goatcounter !== "undefined";
  }

  function buildWidget() {
    const root = document.createElement("section");
    root.className = "hmp-feedback";
    root.setAttribute("aria-label", "Page feedback");

    const heading = document.createElement("p");
    heading.className = "hmp-feedback-question";
    heading.textContent = "Was this page helpful?";
    root.appendChild(heading);

    const buttons = document.createElement("div");
    buttons.className = "hmp-feedback-buttons";

    function record(value) {
      if (isAnalyticsReady()) {
        try {
          window.goatcounter.count({
            path: `feedback/${value}` + window.location.pathname,
            title: document.title || window.location.pathname,
            event: true,
          });
        } catch (error) {
          // Analytics failures are non-fatal.
        }
      }
      root.dataset.recorded = value;
      buttons.querySelectorAll("button").forEach((button) => {
        button.disabled = true;
      });
      const ack = document.createElement("p");
      ack.className = "hmp-feedback-ack";
      ack.textContent =
        value === "yes" ? "Thanks for the signal." : "Thanks. Open an issue if you can describe the gap.";
      root.appendChild(ack);
    }

    [
      ["yes", "Yes"],
      ["no", "No"],
    ].forEach(([value, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.className = `hmp-feedback-button hmp-feedback-${value}`;
      button.addEventListener("click", () => record(value));
      buttons.appendChild(button);
    });

    root.appendChild(buttons);
    return root;
  }

  function injectWidget() {
    const article = document.querySelector("article.bd-article, main");
    if (!article || article.dataset.hmpFeedback === "1") return;
    article.dataset.hmpFeedback = "1";
    article.appendChild(buildWidget());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectWidget);
  } else {
    injectWidget();
  }
})();
