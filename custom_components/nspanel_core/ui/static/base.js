var _last_dropdown_id_activated = "";
var _last_collapse_id_activated = "";

// HA access token for authenticated API calls. The UI runs in HA's sidebar
// iframe (same origin). Primary source: the live token HA pushes to our
// panel element (panel.js forwards hass.auth via postMessage) — works even
// with empty/partitioned browser storage. Fallback: HA's stored tokens in
// localStorage ("Remember me") or sessionStorage (unchecked), in every
// reachable same-origin scope, mirroring the frontend.
// Sent as Authorization: Bearer on every htmx/fetch call and as the STOMP
// CONNECT access_token header. Document loads (iframe src) can't carry it,
// which is why only XHR/mutations require auth server-side.
function nspanelTokenStore() {
  // Returns {store, raw} for the first scope holding usable tokens.
  var scopes = [];
  try { scopes.push(window.localStorage); } catch (e) {}
  try { scopes.push(window.sessionStorage); } catch (e1) {}
  try { if (window.parent && window.parent !== window) { scopes.push(window.parent.localStorage); scopes.push(window.parent.sessionStorage); } } catch (e2) {}
  try { if (window.top && window.top !== window && window.top !== window.parent) { scopes.push(window.top.localStorage); scopes.push(window.top.sessionStorage); } } catch (e3) {}
  for (var i = 0; i < scopes.length; i++) {
    try {
      var raw = scopes[i].getItem("hassTokens");
      if (raw) {
        var tok = JSON.parse(raw);
        if (tok && tok.access_token) return { store: scopes[i], raw: raw, tokens: tok };
      }
    } catch (e4) {}
  }
  return null;
}
// Live token pushed by the panel frame (panel.js forwards HA's own live
// hass.auth token via postMessage). Same-origin only; in-memory only, never
// persisted. Takes precedence over stored tokens because it tracks the live
// HA session even when browser storage is empty, partitioned, or wiped by
// privacy tools. Storage-based lookup below remains as fallback.
var nspanelLiveToken = "";
try {
  window.addEventListener("message", function (ev) {
    try {
      if (!ev || ev.origin !== window.location.origin) return;
      var d = ev.data;
      if (d && d.type === "nspanel-hass-token" && typeof d.access_token === "string" && d.access_token) {
        nspanelLiveToken = d.access_token;
        nspanelEnsureSession();  // P287: rotate the session with the token
        // Hide the login banner directly (cheap DOM removal; the global
        // nspanelRecheckLogin would also work here).
        try {
          var bar = document.getElementById("nspanel-login-banner");
          if (bar) bar.remove();
        } catch (e2) {}
      }
    } catch (e) {}
  });
} catch (e) {}
function nspanelGetToken() {
  try {
    if (typeof nspanelLiveToken === "string" && nspanelLiveToken) return nspanelLiveToken;
  } catch (e) {}
  try {
    var found = nspanelTokenStore();
    if (found && found.tokens && found.tokens.access_token) return found.tokens.access_token;
  } catch (e2) {}
  /* P282: the URL fallback — panel.js passes the live token as ?ha_token=
   * on the iframe URL; remote browsers with partitioned/empty storage get
   * their credential here instead of going out unauthenticated. */
  try {
    var u = new URLSearchParams(window.location.search);
    var t = u.get("ha_token");
    if (t) return t;
  } catch (e3) {}
  return "";
}

// Top-level auth helpers (must live outside $(document).ready so
// stomp_wrapper.js and the submit handler can call them via typeof checks).
function nspanelShowLoginBanner() {
  try {
    if (document.getElementById("nspanel-login-banner")) return;
    var bar = document.createElement("div");
    bar.id = "nspanel-login-banner";
    bar.setAttribute("style", "background:#7a2e2e;color:#fff;padding:10px 16px;font-size:14px;text-align:center;position:sticky;top:0;z-index:9999;");
    bar.innerHTML = 'NSPanel Core actions need a Home Assistant login in this browser tab (open the panel from inside Home Assistant, not via a direct link). <a href="/" style="color:#fff;font-weight:bold;text-decoration:underline;">Open Home Assistant login</a> &middot; <a href="#" id="nspanel-login-recheck" style="color:#fff;font-weight:bold;text-decoration:underline;">Check again</a>';
    var mount = function () {
      try {
        if (document.body && !document.getElementById("nspanel-login-banner")) document.body.prepend(bar);
        var again = document.getElementById("nspanel-login-recheck");
        if (again) again.addEventListener("click", function (ev) {
          ev.preventDefault();
          try {
            if (nspanelHasToken()) { document.getElementById("nspanel-login-banner").remove(); window.location.reload(); }
            else { alert("Still no login found in this tab. Log in to Home Assistant first (same address as this page), then come back."); }
          } catch (e) {}
        });
      } catch (e) {}
    };
    if (document.body) mount();
    else document.addEventListener("DOMContentLoaded", mount, { once: true });
  } catch (e) {}
}
function nspanelHideLoginBanner() {
  try {
    var bar = document.getElementById("nspanel-login-banner");
    if (bar) bar.remove();
  } catch (e) {}
}
function nspanelHasToken() {
  return !!nspanelGetToken();
}
function nspanelRecheckLogin() {
  try {
    if (nspanelHasToken()) nspanelHideLoginBanner();
    else nspanelShowLoginBanner();
  } catch (e) {}
}
var _nspSessionToken = "";
var _nspanelSessionEstablished = false;

/* P311: the HA companion app delivers auth via the frontend's own hass.
 * Reach it through the same-origin iframe chain and either extract a token
 * or use fetchWithAuth (the app-native mechanism) directly. */
let _nspanelFrontendHassCache = undefined; // undefined=unknown, null=absent
function nspanelFindFrontendHassSync() {
  let w = window;
  for (let hop = 0; hop < 5 && w; hop++) {
    try {
      if (w.document && w.document.querySelector) {
        const ha = w.document.querySelector("home-assistant");
        if (ha && ha.hass && ha.hass.auth) return ha.hass;
      }
    } catch (e) {}
    w = (w.parent && w.parent !== w) ? w.parent : null;
  }
  return null;
}
function nspanelFrontendHass() {
  const found = nspanelFindFrontendHassSync();
  if (found) { _nspanelFrontendHassCache = found; return Promise.resolve(found); }
  if (_nspanelFrontendHassCache) return Promise.resolve(_nspanelFrontendHassCache);
  return Promise.resolve(null);
}

async function nspanelExtractTokenFromHass(h) {
  try {
    const a = h && h.auth;
    if (!a) return "";
    let tok = (a.data && a.data.access_token) ||
              (typeof a.accessToken === "string" ? a.accessToken : "") ||
              (a.tokens && a.tokens.access_token) || "";
    if (tok) return tok;
    if (typeof a.getAccessToken === "function") {
      try { tok = await a.getAccessToken(); } catch (e1) {}
    }
    if (!tok && typeof a.refreshAccessToken === "function") {
      try { await a.refreshAccessToken(); } catch (e2) {}
      tok = (a.data && a.data.access_token) ||
            (typeof a.accessToken === "string" ? a.accessToken : "") ||
            (a.tokens && a.tokens.access_token) || "";
    }
    return (typeof tok === "string" ? tok : "") || "";
  } catch (e) { return ""; }
}

async function nspanelEnsureSession() {
  try {
    if (_nspanelSessionEstablished) return true;
    const tok = nspanelGetToken();
    if (tok) {
      if (tok === _nspSessionToken) { _nspanelSessionEstablished = true; return true; }
      _nspSessionToken = tok;
      const resp = await fetch("/nspanel_core/auth_session", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + tok
        },
        body: "{}"
      });
      if (resp && resp.ok) { _nspanelSessionEstablished = true; try { window._nspanelSessionEstablished = true; } catch (e1) {} return true; }
    }
    // No token string? Use the frontend's own auth to establish the session.
    const fh = await nspanelFrontendHass();
    if (fh && typeof fh.fetchWithAuth === "function") {
      const resp = await fh.fetchWithAuth("/nspanel_core/auth_session", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
      if (resp && resp.ok) { _nspanelSessionEstablished = true; try { window._nspanelSessionEstablished = true; } catch (e1) {} return true; }
    }
    return false;
  } catch (e) { return false; }
}

var _nspanelBootstrapDone = false;
try { window._nspanelBootstrapDone = false; window._nspanelSessionEstablished = false; } catch (e) {}
async function nspanelBootstrapFromFrontend(force) {
  try {
    if (!force && _nspanelBootstrapDone) return nspanelGetToken() || "session";
    const fh = await nspanelFrontendHass();
    if (!fh) {
      // try direct extraction from chain even if hass.auth shape odd
      return nspanelGetToken();
    }
    let tok = nspanelGetToken();
    if (!tok) tok = await nspanelExtractTokenFromHass(fh);
    if (tok) {
      nspanelLiveToken = tok;
      try { nspanelHideLoginBanner(); } catch (e1) {}
    }
    const ok = await nspanelEnsureSession();
    if (ok || tok) { _nspanelBootstrapDone = true; return tok || "session"; }
    return "";
  } catch (e) { return ""; }
}

(function nspanelBootstrapRetry() {
  let tries = 0;
  const tick = async function () {
    tries++;
    try {
      const got = await nspanelBootstrapFromFrontend(false);
      if (got) {
        try { htmx.trigger(document.body, "nspanel:auth-ready"); } catch (e1) {}
        // also trigger the nspanels section if waiting
        try { var sec = document.getElementById("nspanels_section"); if (sec) htmx.trigger(sec, "register_request"); } catch (e2) {}
      }
      if (_nspanelBootstrapDone) return;
    } catch (e) {}
    if (tries < 40) setTimeout(tick, 1000);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { tick(); });
  } else {
    tick();
  }
})();

async function nspanelFetchOnce(url, options) {
  options = options || {};
  var headers = Object.assign({}, options.headers || {});
  try { await nspanelRefreshTokenIfNeeded(); } catch (err) {}
  var tok = nspanelGetToken();
  if (tok) headers["Authorization"] = "Bearer " + tok;
  return fetch(url, Object.assign({}, options, { headers: headers, credentials: options.credentials || "same-origin" }));
}

async function nspanelFetch(url, options) {
  var resp = await nspanelFetchOnce(url, options);
  if (resp && resp.status === 401) {
    try { await nspanelRefreshTokenIfNeeded(true); } catch (e) {}
    try { await nspanelBootstrapFromFrontend(true); } catch (e2) {}
    resp = await nspanelFetchOnce(url, options);
  }
  /* P311 (the HA companion app): route through the frontend's own auth. */
  if (resp && resp.status === 401) {
    const fh = await nspanelFrontendHass();
    if (fh && typeof fh.fetchWithAuth === "function") {
      try { resp = await fh.fetchWithAuth(url, options); } catch (e3) {}
    }
  }
  return resp;
}

async function nspanelRefreshTokenIfNeeded(force) {
  var found = null;
  try { found = nspanelTokenStore(); } catch (e) { return; }
  if (!found || !found.tokens || !found.tokens.refresh_token) return;
  var tok = found.tokens;
  var expiresAt = tok.expires || 0;
  if (!force && expiresAt - Date.now() > 120000) return; // still fresh
  try {
    var body = "grant_type=refresh_token&refresh_token=" + encodeURIComponent(tok.refresh_token) +
               "&client_id=" + encodeURIComponent(nspanelClientId());
    var resp = await fetch("/auth/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body,
    });
    if (!resp.ok) return;
    var fresh = await resp.json();
    tok.access_token = fresh.access_token;
    tok.expires_in = fresh.expires_in;
    tok.expires = Date.now() + fresh.expires_in * 1000;
    tok.token_type = "Bearer";
    try { found.store.setItem("hassTokens", JSON.stringify(tok)); } catch (e) {}
  } catch (e) { /* offline — keep the old token; calls will 401 visibly */ }
}

document.addEventListener("htmx:configRequest", function (e) {
  var tok = nspanelGetToken();
  if (tok) e.detail.headers["Authorization"] = "Bearer " + tok;
});

// Close any open modal dialogs (used by modal buttons across pages).
function close_modals() {
  document.querySelectorAll("dialog.modal[open], dialog[open]").forEach((d) => {
    try { d.close(); } catch (e) {}
  });
  var modal = document.getElementById("modal");
  if (modal) {
    try { modal.close(); } catch (e) {}
    modal.remove();
  }
  document.querySelectorAll(".modal-backdrop").forEach((b) => b.remove());
}

// jQuery XHR (entity pickers, legacy posts) carries the same bearer token.
if (typeof $ !== "undefined" && $.ajaxSetup) {
  $.ajaxSetup({
    beforeSend: function (xhr, settings) {
      if (settings.url && settings.url.indexOf("/nspanel_core/") === 0) {
        var tok = nspanelGetToken();
        if (tok) xhr.setRequestHeader("Authorization", "Bearer " + tok);
      }
    },
  });
}

// Full-page forms can't set headers, so authed document forms are submitted
// via fetch with the bearer token; the server redirects are followed here.
document.addEventListener("submit", function (e) {
  var form = e.target;
  if (!form || !form.hasAttribute || !form.hasAttribute("data-authed")) return;
  e.preventDefault();
  (async function () {
    try { await nspanelRefreshTokenIfNeeded(); } catch (err) {}
    var tok = nspanelGetToken();
    var headers = {};
    if (tok) headers["Authorization"] = "Bearer " + tok;
    fetch(form.action, { method: form.method || "POST", body: new FormData(form), headers: headers, redirect: "follow" })
      .then(async function (resp) {
      if (resp.ok) {
        window.location.href = resp.url;
      } else if (resp.status === 401) {
        alert("Not authorized — please log in to Home Assistant first.");
      } else {
        var detail = "";
        try { detail = (await resp.text()).slice(0, 300); } catch (e) {}
        alert("Save failed (HTTP " + resp.status + ")" + (detail ? ": " + detail : ""));
      }
    })
    .catch(function (err) { alert("Save failed: " + err); });
  })();
});

function attach_cursor_change_events() {
  $(".cursor-grab")
    .on("mousedown", function () {
      $(this).removeClass("cursor-grab");
      $(this).addClass("cursor-grabbing");
    })
    .on("mouseup", function () {
      $(this).addClass("cursor-grab");
      $(this).removeClass("cursor-grabbing");
    });
}

$(document).ready(function () {
  console.log("Document ready, attaching functions.");

  stomp_subscribe("mqttmanager/events", (frame) => {
    var json_data = JSON.parse(frame.body);
    if (json_data.event_type) {
      console.log("Triggering custom event: " + json_data.event_type);
      const trigger_event = new CustomEvent(json_data.event_type, {
        detail: json_data,
      });
      document.getElementsByTagName("body")[0].dispatchEvent(trigger_event);
    }
  });

  // Listen for warnings from MQTTManager
  stomp_subscribe("mqttmanager/warnings", (data) => {
    var json = JSON.parse(data.body);
    var warnings = json.warnings;
    // Remove any removed warnings
    $(
      `#error_toast_container > .alert[data-error-source='${ERROR_TOAST_SOURCE_MANAGER}']`,
    ).each(function () {
      let found = false;
      let match_text = $(this).find(".toast-text").text();
      for (let i = 0; i < warnings.length; i++) {
        if (warnings[i].text === match_text) {
          found = true;
          return;
        }
      }

      if (!found) {
        remove_error_toast_element_by_id(this.getAttribute("id"));
      }
    });

    for (let i = 0; i < warnings.length; i++) {
      // Check so that identical warnings are not shown multiple times
      let found = false;
      $("#error_toast_container > .alert").each(function () {
        if ($(this).find(".toast-text").text() == warnings[i].text) {
          found = true;
          return;
        }
      });

      if (!found) {
        show_error_toast(
          warnings[i].level,
          warnings[i].text,
          ERROR_TOAST_SOURCE_MANAGER,
        );
      }
    }
  });

  // Login state: NSPanel Core pages are public documents (an iframe cannot
// send Authorization headers on navigation), so without a session the UI
// renders but every action fails with 401. That usually means this tab was
// opened directly (bookmark/typed URL) instead of from inside Home
// Assistant, or the session here expired — the login lives per address, so
// working HA elsewhere doesn't carry over. Say so plainly with a way back
// into HA's own login flow — never ask the user to handle tokens by hand.
// (nspanelShowLoginBanner/Hide/HasToken/Recheck live at top level so the
// message listener and stomp_wrapper resolve the same copies.)

try {
  // Check now, once more shortly after load (the parent SPA may still be
  // writing its tokens when we first run), and whenever storage changes
  // (e.g. login completed in another tab).
  nspanelRecheckLogin();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { setTimeout(nspanelRecheckLogin, 3000); }, { once: true });
  } else {
    setTimeout(nspanelRecheckLogin, 3000);
  }
  window.addEventListener("storage", function (e) {
    if (!e || !e.key || e.key === "hassTokens") nspanelRecheckLogin();
  });
} catch (e) {}

// Proactively refresh the HA access token when it is about to expire.
// (implementation lives at top level so stomp_wrapper + submit handlers work)
  // Refresh on load and periodically so authed calls rarely hit expiry.
  try { nspanelRefreshTokenIfNeeded(); } catch (e) {}
  setInterval(function () { try { nspanelRefreshTokenIfNeeded(); } catch (e) {} }, 60000);

  // HTMX request failures. On 401 (common in the HA companion app while
  // auth is still being established) attempt bootstrap/session recovery and
  // retry before surfacing an error. Retries are throttled to avoid storms.
  var _nspanel401ToastShown = false;
  var _nspanel401GlobalRecovery = null;
  document.addEventListener("htmx:responseError", (event) => {
    var xhr = event.detail.xhr;
    var status = xhr ? xhr.status : 0;
    var body = "";
    try { body = (xhr.responseText || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200); } catch (e) {}
    if (status === 401) {
      var elt = event.detail.elt || event.detail.target;
      var now = Date.now();
      try {
        if (!elt) elt = document.body;
        elt.__nspanel401Count = (elt.__nspanel401Count || 0) + 1;
        if (elt.__nspanel401RetryAt && (now - elt.__nspanel401RetryAt) < 2500) {
          return; // a retry was just scheduled for this element
        }
      } catch (e0) {}
      var count = (elt && elt.__nspanel401Count) || 1;
      if (count <= 4) {
        try { if (elt) elt.__nspanel401RetryAt = now; } catch (e1) {}
        if (!_nspanel401GlobalRecovery) {
          _nspanel401GlobalRecovery = (async function () {
            try { await nspanelBootstrapFromFrontend(true); } catch (e2) {}
            try { await nspanelEnsureSession(); } catch (e3) {}
          })().finally(function () {
            setTimeout(function () { _nspanel401GlobalRecovery = null; }, 1500);
          });
        }
        setTimeout(function () {
          try {
            if (elt && elt.isConnected && elt.getAttribute && (elt.getAttribute("hx-get") || elt.getAttribute("hx-post") || elt.getAttribute("hx-put") || elt.getAttribute("hx-delete"))) {
              htmx.trigger(elt, "register_request");
              htmx.trigger(elt, "load");
              return;
            }
          } catch (e4) {}
          try {
            var sec = document.getElementById("nspanels_section");
            if (sec) htmx.trigger(sec, "register_request");
          } catch (e5) {}
        }, 700);
        return;
      }
      if (!_nspanel401ToastShown) {
        _nspanel401ToastShown = true;
        show_error_toast(
          0,
          "Not authorized (HTTP 401). Log out and back in to Home Assistant, reload this page, and try again." + (body ? " Server said: " + body : ""),
          ERROR_TOAST_SOURCE_WEB_INTERFACE,
        );
      }
      try { nspanelRefreshTokenIfNeeded(true); } catch (e6) {}
      try { nspanelBootstrapFromFrontend(true); } catch (e7) {}
      return;
    }
    // Successful non-401 path elsewhere will not clear this automatically,
    // but avoid spamming repeated 401 toasts during one broken session.
    try {
      const obj = JSON.parse(xhr.response);
      if (obj && obj.status == "error") {
        show_error_toast(0, obj.text || "Request error but no message specified.", ERROR_TOAST_SOURCE_MANAGER);
        return;
      }
    } catch (error) { /* not JSON — fall through to status/body */ }
    show_error_toast(
      0,
      "Request failed (HTTP " + status + ")" + (body ? ": " + body : "."),
      ERROR_TOAST_SOURCE_MANAGER,
    );
  });

  // Use custom confirm modal with HTMX
  document.addEventListener("htmx:confirm", function (e) {
    // The event is triggered on every trigger for a request, so we need to check if the element
    // that triggered the request has a hx-confirm attribute, if not we can return early and let
    // the default behavior happen
    if (!e.detail.target.hasAttribute("hx-confirm")) return;

    e.preventDefault();

    dialog = document.getElementById("modal_confirm");
    document
      .getElementById("modal_confirm_button")
      .addEventListener("click", function handle_confirm_click(event) {
        // Remove this event listener so that it doesn't trigger multiple times
        event.currentTarget.removeEventListener("click", handle_confirm_click);
        console.log("Sending request");
        document.getElementById("modal_confirm").close();
        e.detail.issueRequest(true);
      });

    document
      .getElementById("modal_confirm_cancel_button")
      .addEventListener("click", function handle_confirm_cancel_click(event) {
        event.currentTarget.removeEventListener(
          "click",
          handle_confirm_cancel_click,
        );
        document.getElementById("modal_confirm").close();
      });

    document.getElementById("modal_confirm_text").textContent = e.detail.question;
    dialog.showModal();
  });

  $("[data-dropdown-toggle]").click(function (e) {
    var toggle_id = $(this).data("dropdown-toggle");
    if (
      _last_dropdown_id_activated != "" &&
      _last_dropdown_id_activated != toggle_id
    ) {
      $("#" + _last_dropdown_id_activated).addClass("hidden");
    }
    $("#" + toggle_id).toggleClass("hidden");
    _last_dropdown_id_activated = toggle_id;
    if (e.stopPropagation) e.stopPropagation();
  });

  $("[data-collapse-toggle]").click(function (e) {
    var toggle_id = $(this).data("collapse-toggle");
    if (
      _last_collapse_id_activated != "" &&
      _last_collapse_id_activated != toggle_id
    ) {
      $("#" + _last_collapse_id_activated).addClass("max-md:hidden");
    }
    $("#" + toggle_id).toggleClass("max-md:hidden");
    _last_collapse_id_activated = toggle_id;
  });

  $(document).on("click", function (e) {
    // Close any open dropdown
    if (_last_dropdown_id_activated != "") {
      $("#" + _last_dropdown_id_activated).addClass("hidden");
    }
  });

  // Setup filename display when uploading files
  $("#firmware").change(() => {
    var filename = $("#firmware")
      .val()
      .replace(/C:\\fakepath\\/i, "");
    $("#save_new_firmware_modal_subtext").text(
      "Selected file: '" + filename + "'.",
    );
    $("#firmware_upload_submit_button").removeClass("btn-disabled");
  });

  $("#data_file").change(() => {
    var filename = $("#data_file")
      .val()
      .replace(/C:\\fakepath\\/i, "");
    $("#save_new_data_file_modal_subtext").text(
      "Selected file: '" + filename + "'.",
    );
    $("#data_file_upload_submit_button").removeClass("btn-disabled");
  });

  $("#tft_file").change(() => {
    var filename = $("#tft_file")
      .val()
      .replace(/C:\\fakepath\\/i, "");
    $("#save_new_tft_file_modal_subtext").text(
      "Selected file: '" + filename + "'.",
    );
    $("#tft_upload_submit_button").removeClass("btn-disabled");
  });

  // Setup drag and drop feature
  $("#firmware_dragdrop_target").on("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  $("#firmware_dragdrop_target").on("dragenter", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  $("#data_file_dragdrop_target").on("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  $("#data_file_dragdrop_target").on("dragenter", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  $("#tft_dragdrop_target").on("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  $("#tft_dragdrop_target").on("dragenter", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });

  $("#firmware_dragdrop_target").on("drop", (e) => {
    if (
      e.originalEvent.dataTransfer &&
      e.originalEvent.dataTransfer.files.length
    ) {
      e.preventDefault();
      e.stopPropagation();
      $("#firmware").prop("files", e.originalEvent.dataTransfer.files);
      var filename = $("#firmware")
        .val()
        .replace(/C:\\fakepath\\/i, "");
      $("#save_new_firmware_modal_subtext").text(
        "Selected file: '" + filename + "'.",
      );
      $("#firmware_upload_submit_button").removeClass("btn-disabled");
    }
  });

  $("#data_file_dragdrop_target").on("drop", (e) => {
    if (
      e.originalEvent.dataTransfer &&
      e.originalEvent.dataTransfer.files.length
    ) {
      e.preventDefault();
      e.stopPropagation();
      $("#data_file").prop("files", e.originalEvent.dataTransfer.files);
      var filename = $("#data_file")
        .val()
        .replace(/C:\\fakepath\\/i, "");
      $("#save_new_data_file_modal_subtext").text(
        "Selected file: '" + filename + "'.",
      );
      $("#data_file_upload_submit_button").removeClass("btn-disabled");
    }
  });

  $("#tft_dragdrop_target").on("drop", (e) => {
    if (
      e.originalEvent.dataTransfer &&
      e.originalEvent.dataTransfer.files.length
    ) {
      e.preventDefault();
      e.stopPropagation();
      $("#tft_file").prop("files", e.originalEvent.dataTransfer.files);
      var filename = $("#tft_file")
        .val()
        .replace(/C:\\fakepath\\/i, "");
      $("#save_new_tft_file_modal_subtext").text(
        "Selected file: '" + filename + "'.",
      );
      $("#tft_upload_submit_button").removeClass("btn-disabled");
    }
  });

  // Attach event listener for cursor-grab to change it to grabing on mouse down for drag & drop targets
  attach_cursor_change_events();
});
