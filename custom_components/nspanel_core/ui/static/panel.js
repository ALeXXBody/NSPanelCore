/**
 * NSPanel Core sidebar panel (panel_custom, embed_iframe).
 *
 * Home Assistant loads this module inside the panel's shim iframe and then
 * creates an <nspanel-core-panel> element. The element embeds the actual
 * NSPanel Core UI (/nspanel_core) so it fills the whole content area with no
 * hass-subpage title bar above it.
 */
class NSPanelCorePanel extends HTMLElement {
  connectedCallback() {
    if (this._iframe) return;

    const url =
      (this.panel && this.panel.config && this.panel.config.url) ||
      "/nspanel_core";

    this.style.cssText = "display:block;width:100%;height:100vh;";

    const iframe = document.createElement("iframe");
    iframe.src = url;
    iframe.title = "NSPanel Core";
    iframe.style.cssText =
      "border:0;width:100%;height:100%;display:block;background:transparent;";

    this._iframe = iframe;
    this.appendChild(iframe);
  }
}

customElements.define("nspanel-core-panel", NSPanelCorePanel);
