(function () {
  // Replaces Material's header logo with a text "Cheatsheet" pill linking to
  // the homepage, where the cheatsheet lives. The logo is hidden in CSS
  // (keyed off the data attribute set below), not removed, so Material's own
  // markup is untouched.
  function readConfig() {
    var el = document.getElementById("md-cheatsheet-config");
    if (!el) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (e) {
      return null;
    }
  }

  function normalize(path) {
    return path.replace(/index\.html$/, "").replace(/\/?$/, "/");
  }

  function render() {
    var config = readConfig();
    var existing = document.querySelector(".md-cheatsheet-button");
    if (existing) existing.remove();
    if (!config) return;

    var title = document.querySelector(".md-header__title");
    var logo = document.querySelector(".md-header__button.md-logo");
    if (!title || !logo) return;

    document.documentElement.setAttribute("data-md-cheatsheet-button", "");

    var link = document.createElement("a");
    link.className = "md-cheatsheet-button";
    link.href = logo.getAttribute("href");
    link.textContent = config.label;

    if (normalize(new URL(link.href, location.href).pathname) === normalize(location.pathname)) {
      link.classList.add("md-cheatsheet-button--active");
      link.setAttribute("aria-current", "page");
    }

    title.insertAdjacentElement("beforebegin", link);
  }

  if (window.document$) {
    window.document$.subscribe(render);
  } else {
    document.addEventListener("DOMContentLoaded", render);
  }
})();
