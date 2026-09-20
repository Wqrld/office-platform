/* The app switcher (la gaufre) for Calendars, served from Calendars' own origin.
 *
 * Calendars draws the waffle BUTTON itself: `LaGaufreV2` from `@gouvfr-lasuite/ui-components`
 * renders it in the header and then hands the PANEL to a widget script it loads from
 * `FRONTEND_LAGAUFRE_WIDGET_PATH` — by default `static.suite.anct.gouv.fr/widgets/lagaufre.js`,
 * which fetches the French government's service list. Unlike Drive's, both of those are
 * runtime settings (`FRONTEND_LAGAUFRE_*` in release.yaml), so nothing has to be hidden and
 * no button has to be re-implemented: this file is a drop-in replacement for that script,
 * `services.json` beside it for that list, and no request leaves our own domains.
 *
 * THE CONTRACT WITH THE REACT COMPONENT, read off ui-components 1.0.0 and the upstream
 * widget it expects:
 *
 *     window._lasuite_widget.push(["lagaufre", "init", cfg])
 *
 * `_lasuite_widget` is a queue: entries pushed BEFORE this script runs are waiting in the
 * array, and entries pushed AFTER must be seen too, so `push` is replaced rather than the
 * array drained once. The component pushes from a `useEffect` that re-runs on re-render, and
 * removes any element with id `lasuite-widget-lagaufre-shadow` before each push — so the
 * panel carries that id, and `init` has to be repeatable.
 *
 * `cfg` carries `buttonElement` (the header button, already in the DOM), `position()` (where
 * to put the panel relative to it), `api` (the service list URL) or `data` (the list inline),
 * `showMoreLimit`, and the labels. Everything else it passes is French-government chrome —
 * `headerLogo` is la Suite's logo — and is deliberately ignored.
 *
 * NO DOLLAR SIGNS ANYWHERE IN THIS FILE. `kustomization.yaml` puts it in a ConfigMap
 * WITHOUT the `substitute: disabled` annotation, because `services.json` in the same
 * ConfigMap needs BASE_DOMAIN resolved. Flux substitutes over both keys, so a template
 * literal or a dollar-prefixed name here would come out blanked — in a file no test parses
 * as JavaScript. That is also why the trailing slash below is trimmed by hand rather than
 * with the regexp anchor that would read as one.
 */
(function () {
  "use strict";

  var NAME = "lagaufre";
  var HOST_ID = "lasuite-widget-" + NAME + "-shadow";

  var CSS = [
    ":host{all:initial}",
    ".panel{position:fixed;z-index:2000;width:288px;max-height:60vh;overflow-y:auto;padding:8px;",
    "background:#fff;border:1px solid #e5e5e5;border-radius:12px;box-shadow:0 6px 24px rgba(0,0,0,.18);",
    "font:400 14px/1.2 system-ui,-apple-system,'Segoe UI',sans-serif;color:#1e1e1e;box-sizing:border-box}",
    ".title{font:600 12px/1 system-ui,sans-serif;color:#666;padding:6px 8px 10px;letter-spacing:.04em;text-transform:uppercase}",
    ".item{display:flex;align-items:center;gap:10px;padding:9px 8px;border-radius:8px;",
    "text-decoration:none;color:#1e1e1e;font-weight:500}",
    ".item:hover{background:#f2f2f7}",
    ".item[aria-current]{background:#eef1ff}",
    ".ico{width:22px;height:22px;flex:0 0 22px;display:flex;align-items:center;justify-content:center;",
    "border-radius:6px;background:#ececf3;font:600 11px/1 system-ui,sans-serif;color:#4a4a68;overflow:hidden}",
    ".ico img{width:100%;height:100%;object-fit:contain}",
    ".badge{margin-left:auto;padding:2px 6px;border-radius:10px;background:#eef1ff;color:#3b4cca;",
    "font:700 9px/1 system-ui,sans-serif;text-transform:uppercase;letter-spacing:.3px}",
    ".more{width:100%;margin-top:4px;padding:8px;border:0;border-radius:8px;background:none;cursor:pointer;",
    "color:#626a80;font:500 13px/1 system-ui,sans-serif}",
    ".more:hover{background:#f2f2f7}",
    ".hidden{display:none}",
    ".msg{padding:12px 8px;color:#666}",
  ].join("");

  // One panel at a time. A second init tears the first one down, listeners included: the
  // component re-inits on re-render and a leaked document listener would keep closing a
  // panel that no longer exists.
  var current = null;

  function destroy() {
    if (!current) return;
    current.teardown.forEach(function (off) { off(); });
    if (current.host.parentNode) current.host.parentNode.removeChild(current.host);
    current = null;
  }

  function on(target, type, fn) {
    target.addEventListener(type, fn);
    return function () { target.removeEventListener(type, fn); };
  }

  function icon(service) {
    var ico = document.createElement("span");
    ico.className = "ico";
    if (service.logo) {
      var img = document.createElement("img");
      img.src = service.logo;
      img.alt = "";
      // A logo that 404s must not leave a broken-image glyph in the menu. The upstream
      // widget drops a service with no logo entirely; a letter is more use than nothing.
      img.onerror = function () { img.remove(); ico.textContent = service.name.slice(0, 1); };
      ico.appendChild(img);
    } else {
      ico.textContent = service.name.slice(0, 1);
    }
    return ico;
  }

  function item(service) {
    var a = document.createElement("a");
    a.className = "item";
    a.href = service.url;
    a.setAttribute("role", "menuitem");
    // The application you are already in, marked rather than hidden — the list is the
    // suite's inventory, and a gap in it reads as a missing service.
    var origin = service.url;
    while (origin.charAt(origin.length - 1) === "/") origin = origin.slice(0, -1);
    if (origin === location.origin) a.setAttribute("aria-current", "page");
    a.appendChild(icon(service));
    a.appendChild(document.createTextNode(service.name));
    // `stable` is the norm and says nothing; anything else is worth a badge.
    if (service.maturity && service.maturity !== "stable") {
      var badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = service.maturity;
      a.appendChild(badge);
    }
    return a;
  }

  function init(cfg) {
    destroy();

    var button = cfg.buttonElement;
    if (!button) return;

    var host = document.createElement("div");
    host.id = HOST_ID;
    var root = host.attachShadow({ mode: "open" });
    var style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);

    var panel = document.createElement("div");
    panel.className = "panel hidden";
    panel.setAttribute("role", "menu");
    panel.setAttribute("aria-label", cfg.label || "Applications");
    var title = document.createElement("div");
    title.className = "title";
    title.textContent = cfg.headerLabel || "Office";
    panel.appendChild(title);
    var body = document.createElement("div");
    var msg = document.createElement("div");
    msg.className = "msg";
    msg.textContent = cfg.loadingText || "Loading...";
    body.appendChild(msg);
    panel.appendChild(body);
    root.appendChild(panel);
    document.body.appendChild(host);

    var state = { host: host, teardown: [] };
    current = state;

    function close() {
      panel.classList.add("hidden");
      button.setAttribute("aria-expanded", "false");
    }

    function open() {
      // The button moves with the header, so the panel is placed at open time, not once.
      var where = typeof cfg.position === "function" ? cfg.position() : null;
      if (where) {
        panel.style.cssText = "";
        Object.keys(where).forEach(function (key) {
          var value = where[key];
          panel.style[key] = typeof value === "number" ? value + "px" : value;
        });
      }
      panel.classList.remove("hidden");
      button.setAttribute("aria-expanded", "true");
    }

    state.teardown.push(on(button, "click", function (event) {
      event.stopPropagation();
      if (panel.classList.contains("hidden")) open(); else close();
    }));
    // Clicks inside an open shadow root retarget to the host at document level, so
    // containment on `host` covers the whole panel.
    state.teardown.push(on(document, "click", function (event) {
      if (host.contains(event.target) || button.contains(event.target)) return;
      close();
    }));
    state.teardown.push(on(document, "keydown", function (event) {
      if (event.key === "Escape") close();
    }));

    function render(services) {
      body.innerHTML = "";
      if (!services || !services.length) {
        msg.textContent = "No services found";
        body.appendChild(msg);
        return;
      }
      var limit = cfg.showMoreLimit || 6;
      services.slice(0, limit).forEach(function (service) { body.appendChild(item(service)); });
      if (services.length <= limit) return;

      var rest = document.createElement("div");
      rest.className = "hidden";
      services.slice(limit).forEach(function (service) { rest.appendChild(item(service)); });
      var more = document.createElement("button");
      more.type = "button";
      more.className = "more";
      more.textContent = cfg.viewMoreLabel || "More apps";
      more.addEventListener("click", function () {
        var opened = !rest.classList.toggle("hidden");
        more.textContent = opened
          ? (cfg.viewLessLabel || "Fewer apps")
          : (cfg.viewMoreLabel || "More apps");
      });
      body.appendChild(more);
      body.appendChild(rest);
    }

    if (cfg.data && cfg.data.services) {
      render(cfg.data.services);
    } else if (cfg.api) {
      fetch(cfg.api, { method: "GET" })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          // The panel may have been re-inited while this was in flight.
          if (current === state) render(payload.services);
        })
        .catch(function () {
          if (current === state) msg.textContent = "Failed to load services";
        });
    } else {
      msg.textContent = "No services found";
    }
  }

  function handle(entry) {
    if (entry && entry[0] === NAME && entry[1] === "init") init(entry[2] || {});
  }

  var queue = (window._lasuite_widget = window._lasuite_widget || []);
  var waiting = queue.splice(0, queue.length);
  queue.push = function () {
    for (var i = 0; i < arguments.length; i++) handle(arguments[i]);
    return queue.length;
  };
  waiting.forEach(handle);
})();
