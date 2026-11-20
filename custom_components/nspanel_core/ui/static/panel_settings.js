/* The behavior that belongs to the panel-settings fields.
 *
 * Extracted from edit_nspanel.js (P290): the fields were MOVED into the
 * Dashboard studio's Panel tab (P263/P266), so their behavior had to move with
 * them. This single file is loaded by BOTH the original settings page and the
 * studio — one source for the button-mode/detached-entity/panel-type logic.
 *
 * P312 REWORK: the DETACHED binding is a Home Assistant entity selected
 * DIRECTLY from the live entity list — no lights-in-rooms detour. The
 * dropdowns are filled from /nspanel_core/api/get_all_available_entities,
 * filtered to toggleable domains.
 */

var _NSPANEL_TOGGLE_DOMAINS = [
  "light", "switch", "fan", "input_boolean", "script",
  "automation", "siren", "input_button", "button", "scene", "media_player",
];

function _nspanelFillEntitySelect($sel) {
  var current = ($sel.attr("data-current") || "").trim();
  nspanelFetch("/nspanel_core/api/get_all_available_entities", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var entities = (d && d.home_assistant_entities) || [];
      var opts = '<option value="">Nothing bound (press does nothing)</option>';
      var found = false;
      entities.forEach(function (e) {
        var domain = (e.entity_id || "").split(".")[0];
        if (_NSPANEL_TOGGLE_DOMAINS.indexOf(domain) === -1) return;
        var selected = (e.entity_id === current) ? " selected" : "";
        if (selected) found = true;
        opts += '<option value="' + e.entity_id + '"' + selected + '>' +
                (e.label || e.entity_id) + " · " + e.entity_id + "</option>";
      });
      if (current && !found) {
        // a binding the entity list no longer reports (e.g. HA offline):
        // keep it visible so a save does not silently unbind it
        opts += '<option value="' + current + '" selected>' + current + " (current)</option>";
      }
      $sel.html(opts);
    })
    .catch(function () {
      $sel.html('<option value="">Could not load Home Assistant entities</option>');
      if (current) {
        $sel.html('<option value="' + current + '" selected>' + current + " (current)</option>");
      }
    });
}

function _nspanelFillEntitySelects() {
  $("[data-nspanel-entity-select]").each(function () {
    if (this.dataset.nspanelLoaded === "1") return;
    this.dataset.nspanelLoaded = "1";
    _nspanelFillEntitySelect($(this));
  });
}

function update_shown_elements() {
  $("#button1_detached_mode_controls").addClass("hidden");
  $("#button2_detached_mode_controls").addClass("hidden");
  $("#button1_mqtt_mode_controls").addClass("hidden");
  $("#button2_mqtt_mode_controls").addClass("hidden");

  if ($("#button1_mode").val() == 1) {
    // Detached mode
    $("#button1_detached_mode_controls").removeClass("hidden");
    _nspanelFillEntitySelects();
  } else if ($("#button1_mode").val() == 2) {
    // Custom MQTT mode
    $("#button1_mqtt_mode_controls").removeClass("hidden");
  }

  if ($("#button2_mode").val() == 1) {
    // Detached mode
    $("#button2_detached_mode_controls").removeClass("hidden");
    _nspanelFillEntitySelects();
  } else if ($("#button2_mode").val() == 2) {
    // Custom MQTT mode
    $("#button2_mqtt_mode_controls").removeClass("hidden");
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
}
