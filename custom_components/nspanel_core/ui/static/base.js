var _last_dropdown_id_activated = "";
var _last_collapse_id_activated = "";

// HA access token for authenticated API calls. The UI runs in HA's sidebar
// iframe (same origin), so HA's own tokens in localStorage are readable.
// Sent as Authorization: Bearer on every htmx/fetch call and as the STOMP
// CONNECT access_token header. Document loads (iframe src) can't carry it,
// which is why only XHR/mutations require auth server-side.
function nspanelGetToken() {
  var scopes = [];
  try { scopes.push(window.localStorage); } catch (e) {}
  try { if (window.parent && window.parent !== window) scopes.push(window.parent.localStorage); } catch (e) {}
  try { if (window.top && window.top !== window && window.top !== window.parent) scopes.push(window.top.localStorage); } catch (e) {}
  for (var i = 0; i < scopes.length; i++) {
    try {
      var raw = scopes[i].getItem("hassTokens");
      if (raw) {
        var tok = JSON.parse(raw);
        if (tok && tok.access_token) return tok.access_token;
      }
    } catch (e) {}
  }
  return "";
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
// send Authorization headers on navigation), so a logged-out visitor sees
// the UI but every action 401s. Detect that up front and say so plainly,
// with a link into HA's own login flow — never ask the user to handle
// tokens by hand.
function nspanelShowLoginBanner() {
  try {
    if (document.getElementById("nspanel-login-banner")) return;
    var bar = document.createElement("div");
    bar.id = "nspanel-login-banner";
    bar.setAttribute("style", "background:#7a2e2e;color:#fff;padding:10px 16px;font-size:14px;text-align:center;position:sticky;top:0;z-index:9999;");
    bar.innerHTML = 'You are not logged in to Home Assistant in this browser tab, so NSPanel Core actions will fail. <a href="/" style="color:#fff;font-weight:bold;text-decoration:underline;">Log in to Home Assistant</a>, then reload this page.';
    if (document.body) document.body.prepend(bar);
    else document.addEventListener("DOMContentLoaded", function () { document.body.prepend(bar); }, { once: true });
  } catch (e) {}
}

function nspanelHasToken() {
  return !!nspanelGetToken();
}

try {
  if (!nspanelHasToken()) nspanelShowLoginBanner();
} catch (e) {}

// Proactively refresh the HA access token when it is about to expire.
  // HA access tokens live ~30 min; a stale one makes every authed call
  // 401. The refresh uses the stored refresh_token and updates the same
  // localStorage entry the frontend uses. client_id must match the one
  // used at login (origin with trailing slash).
  function nspanelClientId() {
    var base = "";
    try {
      var raw = window.localStorage.getItem("hassTokens");
      if (raw) base = JSON.parse(raw).hassUrl || "";
    } catch (e) {}
    if (!base) {
      try { base = window.parent.localStorage.getItem("hassTokens"); } catch (e2) {}
      try { if (base) base = JSON.parse(base).hassUrl || ""; } catch (e3) { base = ""; }
    }
    base = base || location.origin;
    return base.replace(/\/+$/, "") + "/";
  }
  async function nspanelRefreshTokenIfNeeded() {
    var raw = null;
    try { raw = window.localStorage.getItem("hassTokens"); } catch (e) { return; }
    if (!raw) return;
    var tok;
    try { tok = JSON.parse(raw); } catch (e) { return; }
    if (!tok || !tok.refresh_token) return;
    var expiresAt = tok.expires || 0;
    if (expiresAt - Date.now() > 120000) return; // still fresh
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
      try { window.localStorage.setItem("hassTokens", JSON.stringify(tok)); } catch (e) {}
    } catch (e) { /* offline — keep the old token; calls will 401 visibly */ }
  }

  // Refresh on load and periodically so authed calls rarely hit expiry.
  try { nspanelRefreshTokenIfNeeded(); } catch (e) {}
  setInterval(function () { try { nspanelRefreshTokenIfNeeded(); } catch (e) {} }, 60000);

  // Something went wrong while sending/processing AJAX request via HTMX. Show error toast.
  // The server usually answers errors as plain text/HTML (not JSON), so
  // surface the HTTP status + body instead of dying in JSON.parse — the old
  // code swallowed every real message behind a generic one.
  document.addEventListener("htmx:responseError", (event) => {
    var xhr = event.detail.xhr;
    var status = xhr ? xhr.status : 0;
    var body = "";
    try { body = (xhr.responseText || "").replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200); } catch (e) {}
    if (status === 401) {
      show_error_toast(
        0,
        "Not authorized (HTTP 401). Log out and back in to Home Assistant, reload this page, and try again." + (body ? " Server said: " + body : ""),
        ERROR_TOAST_SOURCE_WEB_INTERFACE,
      );
      try { nspanelRefreshTokenIfNeeded(); } catch (e) {}
      return;
    }
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
    $("#save_new_firmware_modal_subtext").html(
      "Selected file: '" + filename + "'.",
    );
    $("#firmware_upload_submit_button").removeClass("btn-disabled");
  });

  $("#data_file").change(() => {
    var filename = $("#data_file")
      .val()
      .replace(/C:\\fakepath\\/i, "");
    $("#save_new_data_file_modal_subtext").html(
      "Selected file: '" + filename + "'.",
    );
    $("#data_file_upload_submit_button").removeClass("btn-disabled");
  });

  $("#tft_file").change(() => {
    var filename = $("#tft_file")
      .val()
      .replace(/C:\\fakepath\\/i, "");
    $("#save_new_tft_file_modal_subtext").html(
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
      $("#save_new_firmware_modal_subtext").html(
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
      $("#save_new_data_file_modal_subtext").html(
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
      $("#tft_file").html("Selected file: '" + filename + "'.");
      $("#tft_upload_submit_button").removeClass("btn-disabled");
    }
  });

  // Attach event listener for cursor-grab to change it to grabing on mouse down for drag & drop targets
  attach_cursor_change_events();
});
