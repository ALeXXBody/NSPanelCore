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
        /* P285 THE PROPER FIX: the session cookie — set by this same-origin
         * shim, carried by EVERY navigation to the integration's pages
         * (the sidebar, the Integrations links, new tabs), validated
         * server-side against the HA auth store. */
        document.cookie = "nspanel_token=" + encodeURIComponent(t) +
          "; path=/; max-age=3600; SameSite=Strict";
        // P287: exchange the short-lived HA token for the manager's 24h
        // session cookie. The response sets an httponly cookie that EVERY
        // navigation carries (sidebar, Integrations links, new tabs) —
        // no 5-minute expiry, no referer tricks.
        this._exchangeSession(t);
        // P281: the gated pages verify the token from the URL — keep the
        // iframe's credential current (one src refresh per token rotation)
        if (this._frame) {
          const want = "/nspanel_core/ui?ha_token=" + encodeURIComponent(t);
          if (this._frame.src.indexOf("ha_token=") === -1 ||
              decodeURIComponent(this._frame.src.split("ha_token=")[1] || "") !== t) {
            this._frame.src = want;
          }
        }
      }
    } catch (e) {}
  }

  connectedCallback() {
    if (this._done) return;
    this._done = true;

    this.style.cssText = "display:block;width:100%;height:100%;min-height:100vh;";

    const iframe = document.createElement("iframe");
    iframe.src = this._liveToken
      ? "/nspanel_core/ui?ha_token=" + encodeURIComponent(this._liveToken)
      : "/nspanel_core/ui";
    iframe.title = "NSPanel Core";
    iframe.style.cssText = "border:0;width:100%;height:100%;min-height:100vh;display:block;";
    iframe.setAttribute("allowfullscreen", "");
    this._frame = iframe;
    iframe.addEventListener("load", () => {
      try { this._pushToken(); } catch (e) {}
    });
    this.appendChild(iframe);
  }

  _exchangeSession(token) {
    try {
      fetch("/nspanel_core/auth_session", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer " + token
        },
        body: "{}"
      }).catch(function () {});
    } catch (e) {}
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
