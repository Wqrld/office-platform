/* The app switcher for the apps whose frontends ship none we can use: Drive and Meet.
 *
 * Drive's built-in gaufre loads a widget script from static.suite.anct.gouv.fr and reads
 * the French government's service list, both compiled into the bundle with no runtime
 * override; FRONTEND_JS_URL is the only hook its page offers. Meet has no switcher at all
 * and no hook, so its nginx injects a <script> tag (apps/meet/default.conf). One file
 * serves both: `apps/kustomization.yaml` puts it in a ConfigMap per app, and the only
 * per-app part is where in the page it mounts (MOUNTS, keyed by hostname).
 *
 * Keep the service list here in step with the other two: Docs' `waffle.data.services` and
 * `apps/calendars/services.json`. One list per switcher, and an application added to one and
 * not the rest is missing from a switcher.
 */
(function () {
  "use strict";
  if (window.__officeSwitcher) return;
  window.__officeSwitcher = true;

  var BASE = location.hostname.split(".").slice(1).join(".");
  var SERVICES = [
    { name: "Docs", url: "https://docs." + BASE, icon: "https://docs." + BASE + "/assets/icon-docs.svg" },
    { name: "Drive", url: "https://drive." + BASE, icon: "https://drive." + BASE + "/assets/logo-icon_beta.svg" },
    { name: "Calendars", url: "https://calendars." + BASE, icon: "https://calendars." + BASE + "/favicon.png" },
    { name: "Meet", url: "https://meet." + BASE, icon: "https://meet." + BASE + "/favicon-32x32.png" },
    { name: "Account", url: "https://id." + BASE + "/realms/office/account", icon: null },
  ];

  var css = document.createElement("style");
  css.textContent = [
    ".office-sw{position:relative;display:inline-flex;align-items:center}",
    ".office-sw__btn{display:flex;align-items:center;justify-content:center;width:36px;height:36px;",
    "border:0;border-radius:8px;background:transparent;cursor:pointer;color:#3b3b3b}",
    ".office-sw__btn:hover{background:rgba(0,0,0,.06)}",
    ".office-sw__menu{position:absolute;top:44px;right:0;z-index:2000;min-width:232px;padding:8px;",
    "background:#fff;border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.18);display:none}",
    ".office-sw__menu[data-open]{display:block}",
    ".office-sw__title{font:600 12px/1 system-ui,sans-serif;color:#666;padding:6px 8px 10px;letter-spacing:.04em;text-transform:uppercase}",
    ".office-sw__item{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:8px;",
    "text-decoration:none;color:#1e1e1e;font:500 14px/1.2 system-ui,sans-serif}",
    ".office-sw__item:hover{background:#f2f2f7}",
    ".office-sw__item[aria-current]{background:#eef1ff}",
    ".office-sw__ico{width:22px;height:22px;flex:0 0 22px;display:flex;align-items:center;justify-content:center;",
    "border-radius:6px;background:#ececf3;font:600 11px/1 system-ui,sans-serif;color:#4a4a68;overflow:hidden}",
    ".office-sw__ico img{width:100%;height:100%;object-fit:contain}",
  ].join("");
  document.head.appendChild(css);

  function build() {
    var wrap = document.createElement("div");
    wrap.className = "office-sw";

    var btn = document.createElement("button");
    btn.className = "office-sw__btn";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toepassingen");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">' +
      [0, 7, 14].map(function (y) {
        return [0, 7, 14].map(function (x) {
          return '<rect x="' + x + '" y="' + y + '" width="5" height="5" rx="1.2"/>';
        }).join("");
      }).join("") +
      "</svg>";

    var menu = document.createElement("div");
    menu.className = "office-sw__menu";
    menu.setAttribute("role", "menu");
    var title = document.createElement("div");
    title.className = "office-sw__title";
    title.textContent = "Office";
    menu.appendChild(title);

    SERVICES.forEach(function (s) {
      var a = document.createElement("a");
      a.className = "office-sw__item";
      a.href = s.url;
      a.setAttribute("role", "menuitem");
      if (location.origin === s.url) a.setAttribute("aria-current", "page");
      var ico = document.createElement("span");
      ico.className = "office-sw__ico";
      if (s.icon) {
        var img = document.createElement("img");
        img.src = s.icon;
        img.alt = "";
        // A missing icon must not leave a broken-image glyph in the menu.
        img.onerror = function () { ico.textContent = s.name.slice(0, 1); img.remove(); };
        ico.appendChild(img);
      } else {
        ico.textContent = s.name.slice(0, 1);
      }
      a.appendChild(ico);
      a.appendChild(document.createTextNode(s.name));
      menu.appendChild(a);
    });

    function close() { menu.removeAttribute("data-open"); btn.setAttribute("aria-expanded", "false"); }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = menu.hasAttribute("data-open");
      if (open) return close();
      menu.setAttribute("data-open", "");
      btn.setAttribute("aria-expanded", "true");
    });
    document.addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    menu.addEventListener("click", function (e) { e.stopPropagation(); });

    wrap.appendChild(btn);
    wrap.appendChild(menu);
    return wrap;
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
      if (host) { host.appendChild(build()); return true; }
    }
    return false;
  }

  function mountFixed() {
    if (document.querySelector(".office-sw")) return;
    var w = build();
    w.style.cssText = "position:fixed;left:12px;bottom:12px;z-index:2000";
    w.querySelector(".office-sw__menu").style.cssText = "top:auto;bottom:44px;left:0;right:auto";
    document.body.appendChild(w);
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
