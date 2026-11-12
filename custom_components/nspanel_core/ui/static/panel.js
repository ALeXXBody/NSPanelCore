// NSPanel Core sidebar panel (panel_custom, embed_iframe).
//
// Home Assistant renders a bare <iframe> (no hass-subpage title bar) for
// embed_iframe panels and writes a shim document into it. The shim loads this
// module, which redirects the iframe to the actual NSPanel Core UI so it
// fills the whole content area.
window.location.replace("/nspanel_core");
