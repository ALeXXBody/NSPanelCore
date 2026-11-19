var mac_address;
var nspanel_id;

function push_log_message_to_view(data) {
  var level_tag;
  var level_tag_background;
  if (data.level == "ERROR") {
    level_tag_background = "bg-error";
    level_tag = 'ERROR';
  } else if (data.level == "WARNING") {
    level_tag_background = "bg-warning";
    level_tag = 'WARNING';
  } else if (data.level == "INFO") {
    level_tag_background = "bg-info";
    level_tag = 'INFO';
  } else if (data.level == "DEBUG") {
    level_tag_background = "bg-neutral";
    level_tag = 'DEBUG';
  } else if (data.level == "TRACE") {
    level_tag = 'TRACE';
  } else {
    level_tag = '???UNKNOWN???';
  }
  // Build DOM nodes with text() — never concatenate device-controlled
  // strings into HTML (stored XSS via panel log messages).
  var row = $("<tr class='hover'>");
  row.append($("<td class='py-1'>").text(data.time));
  row.append($("<td class='py-1 text-center " + level_tag_background + "'>").text(level_tag));
  row.append($("<td class='py-1'>").text(data.message));

  var row_count = $("#log_body tr").length;
  if (row_count >= $("#max_live_log_messages").text()) {
    $("#log_body tr:last-child").remove();
  }

  $("#log_body").prepend(row);
}

/* P290: the button-mode / detached-light / panel-type behavior now lives in
 * panel_settings.js — shared with the Dashboard studio, one source. */

$(document).ready(() => {
  document
    .querySelectorAll(".nspanel_settings_container")
    .forEach((element) => {
      // On message from manager on websocket.
      element.addEventListener("htmx:afterRequest", (event) => {
        if (event.detail.successful) {
          window.Location = "/";
        }
      });
    });
  bindPanelSettingsBehavior();  // P290: the shared field behavior

  stomp_subscribe("nspanel/" + nspanel_mac + "/log", (message) => {
    push_log_message_to_view(JSON.parse(message.body));
  });

  // Fetch log backtrace once.
  stomp_subscribe("nspanel/" + nspanel_mac + "/log_backlog", (message) => {
    JSON.parse(message.body).logs.forEach((message) => {
      push_log_message_to_view(message);
    });

    stomp_unsubscribe("nspanel/" + nspanel_mac + "/log_backlog");
  });
});
