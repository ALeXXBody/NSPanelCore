function show_dropdown_menu(e, element) {
  var dropdown_id = $(element).attr("data-nspanel-dropdown-toggle");
  if (dropdown_id != "") {
    $("#" + dropdown_id).toggleClass("hidden");
    if (e.stopPropagation) e.stopPropagation();
  }
}

function show_popover(e) {
  var popover_target = $(e).data("popover-target");
  if (popover_target) {
    $("#" + popover_target).removeClass("invisible opacity-0");
  }
}

function hide_popover(e) {
  var popover_target = $(e).data("popover-target");
  if (popover_target) {
    $("#" + popover_target).addClass("invisible opacity-0");
  }
}

$(window).click(function () {
  $(".nspanel-actions-menu-dropdown").addClass("hidden");
});


// Send a reboot command to all NSPanels

// Send a firmware update command to all online NSPanels

// Send a GUI update command to all online NSPanels
function start_all_nspanels_gui_update_ota() {
  $(".nspanel_info_tag[data-nspanel-state='online']").each((index, obj) => {
    stomp_send(
      "nspanel/" + $(obj).data("nspanel-mac") + "/command",
      "gui_update",
    );
  });
}

// NSPanel Core (integration): when the manager notifies a register_request on
// mqttmanager/events, dispatch the DOM event the NSPanels section listens for.
if (typeof stomp_subscribe === "function") {
  const _registerListener = () => {
    try {
      stomp_subscribe("mqttmanager/events", (frame) => {
        try {
          const data = JSON.parse(frame.body);
          if (data.event_type === "register_request") {
            document.getElementsByTagName("body")[0].dispatchEvent(
              new CustomEvent("register_request", { detail: data })
            );
          }
        } catch (e) { /* ignore */ }
      });
    } catch (e) { /* ignore */ }
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _registerListener);
  } else {
    _registerListener();
  }
}
