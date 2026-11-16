// NSPanel Core sidebar panel (panel_custom, embed_iframe).
//
// Home Assistant renders a bare <iframe> (no hass-subpage title bar) for
// embed_iframe panels and writes a shim document into it. The shim loads this
// module, which renders the NSPanel Core UI in a full-size inner iframe.
//
// Auth strategy: HA pushes live updates (including the hass object) into the
// shim context. If HA assigns .hass to this element, forward the live access
// token to the UI iframe via postMessage — same origin throughout. This does
// NOT depend on browser token storage at all, so it keeps working when
// localStorage/sessionStorage is empty, partitioned, or wiped by privacy
// tools. Storage-based lookup in the UI remains as fallback.
class NSPanelCorePanel extends HTMLElement {
  set hass(h) {
    try {
      const t = h && h.auth && h.auth.data && h.auth.data.access_token;
      if (t && t !== this._liveToken) {
        this._liveToken = t;
        this._pushToken();
      }
    } catch (e) {}
  }

  connectedCallback() {
    if (this._done) return;
    this._done = true;

    this.style.cssText = "display:block;width:100%;height:100%;min-height:100vh;";

    const iframe = document.createElement("iframe");
    iframe.src = "/nspanel_core/ui";
    iframe.title = "NSPanel Core";
    iframe.style.cssText = "border:0;width:100%;height:100%;min-height:100vh;display:block;";
    iframe.setAttribute("allowfullscreen", "");
    this._frame = iframe;
    iframe.addEventListener("load", () => {
      try { this._pushToken(); } catch (e) {}
    });
    this.appendChild(iframe);
  }

  _pushToken() {
    try {
      if (!this._liveToken || !this._frame || !this._frame.contentWindow) return;
      this._frame.contentWindow.postMessage(
        { type: "nspanel-hass-token", access_token: this._liveToken },
        window.location.origin
      );
    } catch (e) {}
  }
}

customElements.define("nspanel-core-panel", NSPanelCorePanel);
