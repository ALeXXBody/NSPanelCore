/* The behavior that belongs to the panel-settings fields.
 *
 * Extracted from edit_nspanel.js (P290): the fields were MOVED into the
 * Dashboard studio's Panel tab (P263/P266), so their behavior had to move with
 * them. This single file is loaded by BOTH the original settings page and the
 * studio — one source for the button-mode/detached-light/panel-type logic.
 */

function update_shown_elements() {
  $("#button1_detached_mode_controls").addClass("hidden");
  $("#button2_detached_mode_controls").addClass("hidden");
  $("#button1_detached_mode_light").addClass("hidden");
  $("#button2_detached_mode_light").addClass("hidden");
  $("#button1_mqtt_mode_controls").addClass("hidden");
  $("#button2_mqtt_mode_controls").addClass("hidden");
  $("#button1_detached_mode_light").prop("required", false);
  $("#button2_detached_mode_light").prop("required", false);

  if ($("#button1_mode").val() == 0) {
    // Direct mode
  } else if ($("#button1_mode").val() == 1) {
    // Detached mode
    $("#button1_detached_mode_controls").removeClass("hidden");
    $("#button1_detached_mode_light").prop("required", true);
    $("#button1_detached_mode_light").removeClass("hidden");
  } else if ($("#button1_mode").val() == 2) {
    // MQTT mode
    $("#button1_mqtt_mode_controls").removeClass("hidden");
  } else if ($("#button1_mode").val() == 3) {
    // Follow mode
  }

  if ($("#button2_mode").val() == 0) {
    // Direct mode
  } else if ($("#button2_mode").val() == 1) {
    // Detached mode
    $("#button2_detached_mode_controls").removeClass("hidden");
    $("#button2_detached_mode_light").prop("required", true);
    $("#button2_detached_mode_light").removeClass("hidden");
  } else if ($("#button2_mode").val() == 2) {
    // MQTT mode
    $("#button2_mqtt_mode_controls").removeClass("hidden");
  } else if ($("#button2_mode").val() == 3) {
    // Follow mode
  }

  // Update shown lights depending on selected room
  var button1_selected_room_id = $("#button1_detached_mode_room").val();
  $(".button1_detached_mode_light_option[data-room-id='" + button1_selected_room_id + "']").show();
  $(".button1_detached_mode_light_option[data-room-id!='" + button1_selected_room_id + "']").hide();

  // Check if selected button1_detached_mode_light option is visible, if not, select the first of the options.
  if ($(".button1_detached_mode_light_option[data-room-id='" + button1_selected_room_id + "']:selected").length == 0) {
    var button1_detached_light_first_value = $(".button1_detached_mode_light_option[data-room-id='" + button1_selected_room_id + "']:first").val();
    if (button1_detached_light_first_value) {
      console.log("Selected option for button1 detached light is no longer accessible in selected room, will select '", button1_detached_light_first_value, "' instead.");
      $("#button1_detached_mode_light").val(button1_detached_light_first_value).change();
    } else {
      $("#button1_detached_mode_light").val("").change();
    }
  }

  var button2_selected_room_id = $("#button2_detached_mode_room").val();
  $(".button2_detached_mode_light_option[data-room-id='" + button2_selected_room_id + "']").show();
  $(".button2_detached_mode_light_option[data-room-id!='" + button2_selected_room_id + "']").hide();

  // Check if selected button2_detached_mode_light option is visible, if not, select the first of the options.
  if ($(".button2_detached_mode_light_option[data-room-id='" + button2_selected_room_id + "']:selected").length == 0) {
    var button2_detached_light_first_value = $(".button2_detached_mode_light_option[data-room-id='" + button2_selected_room_id + "']:first").val();
    if (button2_detached_light_first_value) {
      console.log("Selected option for button2 detached light is no longer accessible in selected room, will select '", button2_detached_light_first_value, "' instead.");
      $("#button2_detached_mode_light").val(button2_detached_light_first_value).change();
    } else {
      $("#button2_detached_mode_light").val("").change();
    }
  }
}

/* Bind the settings fields. Called by the settings page on DOM ready and by
 * the studio AFTER it injects the server-rendered form into the Panel tab —
 * the injected nodes do not exist when the page's ready handler runs. */
function bindPanelSettingsBehavior() {
  if (typeof $ === "undefined") return;
  update_shown_elements();

  $("#button1_mode").change(update_shown_elements);
  $("#button2_mode").change(update_shown_elements);
  $("#screensaver_mode").change(update_shown_elements);
  $("#button1_detached_mode_room").change(update_shown_elements);
  $("#button2_detached_mode_room").change(update_shown_elements);
}
