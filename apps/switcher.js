/* The switcher BUTTON for the apps whose frontends ship none we can use: Drive and Meet.
 *
 * Drive's built-in gaufre loads a widget script from static.suite.anct.gouv.fr and reads
 * the French government's service list, both compiled into the bundle with no runtime
 * override; FRONTEND_JS_URL is the only hook its page offers. Meet has no switcher at all
 * and no hook, so its nginx injects a <script> tag (apps/meet/default.conf). One file
 * serves both, and the only per-app part is where in the page the button mounts (MOUNTS,
 * keyed by hostname).
 *
 * The PANEL is not here. This does what `LaGaufreV2` does in Docs and Calendars: put a
 * button in the page, then hand it to `gaufre.js` — the same panel, the same service list
 * (/custom/services.json, the control plane's, so an app that is off is not in it) — over
 * the widget's queue protocol, which gaufre.js documents. Both files are served from the
 * app's own origin; nothing leaves our domains.
 *
 * No dollar signs in this file: it is in a ConfigMap Flux would otherwise substitute over.
 */
(function () {
  "use strict";
  if (window.__officeSwitcher) return;
  window.__officeSwitcher = true;

  var css = document.createElement("style");
  css.textContent =
    ".office-sw{display:flex;align-items:center;justify-content:center;width:36px;height:36px;" +
    "border:0;border-radius:8px;background:transparent;cursor:pointer;color:#3b3b3b}" +
    ".office-sw:hover{background:rgba(0,0,0,.06)}";
  document.head.appendChild(css);

  function button() {
    var btn = document.createElement("button");
    btn.className = "office-sw";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toepassingen");
    btn.setAttribute("aria-haspopup", "menu");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">' +
      [0, 7, 14].map(function (y) {
        return [0, 7, 14].map(function (x) {
          return '<rect x="' + x + '" y="' + y + '" width="5" height="5" rx="1.2"/>';
        }).join("");
      }).join("") +
      "</svg>";
    return btn;
  }

  // What the ui-kit passes the widget: the panel sits below the button, or above it when
  // the button is in the lower half (the fixed fallback), and is right-aligned to it when
  // there is room for the panel on the left.
  function position(btn) {
    return function () {
      var r = btn.getBoundingClientRect();
      var gap = 10;
      var at = {};
      if (r.top > window.innerHeight / 2) at.bottom = window.innerHeight - r.top + gap;
      else at.top = r.bottom + gap;
      if (r.right >= 340) at.right = window.innerWidth - r.right;
      else at.left = r.left;
      return at;
    };
  }

  function init(btn) {
    (window._lasuite_widget = window._lasuite_widget || []).push(["lagaufre", "init", {
      buttonElement: btn,
      position: position(btn),
      api: "/custom/services.json",
      label: "Toepassingen",
      headerLabel: "Office",
      showMoreLimit: 9,
    }]);
    // Pushed before the script runs is fine: gaufre.js replays the queue it finds.
    if (!document.getElementById("office-gaufre")) {
      var script = document.createElement("script");
      script.id = "office-gaufre";
      script.src = "/custom/gaufre.js";
      script.async = true;
      document.head.appendChild(script);
    }
  }

  // Both apps render their chrome client-side, so wait for it rather than for
  // DOMContentLoaded. Drive: `.c__left-panel__footer__drive` is Drive's own class and is
  // where the gaufre sat (ExplorerLayout.tsx); the header slot comes from the ui-kit and
  // its class name is not ours to rely on, so it is tried by shape. Meet: the header's
  // <nav> holds one Stack with the login/user menu (layout/Header.tsx); in a call there
  // is no header at all. Anything unmatched falls back to a fixed button.
  var MOUNTS = {
    drive: [".c__left-panel__footer__drive", "[class*='header__right']", "[class*='__header'] > *:last-child"],
    meet: ["nav > div"],
  }[location.hostname.split(".")[0]] || [];

  function mount() {
    if (document.querySelector(".office-sw")) return true;
    for (var i = 0; i < MOUNTS.length; i++) {
      var host = document.querySelector(MOUNTS[i]);
      if (host) {
        var btn = button();
        host.appendChild(btn);
        init(btn);
        return true;
      }
    }
    return false;
  }

  function mountFixed() {
    if (document.querySelector(".office-sw")) return;
    var btn = button();
    btn.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2000;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.15)";
    document.body.appendChild(btn);
    init(btn);
  }

  function start() {
    if (mount()) return;
    var obs = new MutationObserver(function () { if (mount()) obs.disconnect(); });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    // If the app never renders a slot we recognise, still give the user a way across.
    setTimeout(function () { obs.disconnect(); mountFixed(); }, 8000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
