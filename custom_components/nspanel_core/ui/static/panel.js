// NSPanel Core sidebar panel (panel_custom, embed_iframe).
//
// Home Assistant renders a bare <iframe> (no hass-subpage title bar) for
// embed_iframe panels and writes a shim document into it. The shim loads this
// module, which renders the NSPanel Core UI in a full-size inner iframe.
class NSPanelCorePanel extends HTMLElement {
  connectedCallback() {
    if (this._done) return;
    this._done = true;

    this.style.cssText = "display:block;width:100%;height:100%;min-height:100vh;";

    const iframe = document.createElement("iframe");
    iframe.src = "/nspanel_core/ui";
    iframe.title = "NSPanel Core";
    iframe.style.cssText = "border:0;width:100%;height:100%;min-height:100vh;display:block;";
    iframe.setAttribute("allowfullscreen", "");
    this.appendChild(iframe);
  }
}

customElements.define("nspanel-core-panel", NSPanelCorePanel);
