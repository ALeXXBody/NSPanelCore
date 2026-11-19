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
      this._hassRef = h;  // P310: keep the live hass for late token polling
      const t = this._extractToken(h);
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
        // P281: the gated pages verify the token from the URL — the iframe
        // NEVER loads without it.
        if (this._frame) this._loadWithToken(t);
      }
    } catch (e) {}
  }

  /* P310 (the companion app): the app delivers the access token ASYNC via
   * its external bus ("externalAuthSetToken" fills auth.data later) — the
   * first `set hass` may run BEFORE any token exists and hass is never
   * reassigned afterwards. Extract from every known shape and keep polling
   * the live hass until a token appears. */
  _extractToken(h) {
    const a = h && h.auth;
    if (!a) return "";
    return (a.data && a.data.access_token) ||
           (typeof a.accessToken === "string" && a.accessToken) ||
           (a.tokens && a.tokens.access_token) ||
           (a.data && a.data.auth && a.data.auth.access_token) || "";
  }

  _startTokenPoll() {
    if (this._poll) return;
    this._pollStart = this._pollStart || Date.now();
    this._poll = setInterval(() => {
      try {
        if (this._liveToken) { clearInterval(this._poll); this._poll = null; return; }
        const h = this._hassRef ||
          (document.querySelector("home-assistant") || {}).hass;
        const tok = this._extractToken(h);
        if (tok && tok !== this._liveToken) {
          this._liveToken = tok;
          this._exchangeSession(tok);
          if (this._frame) this._loadWithToken(tok);
        }
        if (Date.now() - this._pollStart > 120000) {
          clearInterval(this._poll); this._poll = null;
        }
      } catch (e) {}
    }, 2000);
  }

  connectedCallback() {
    if (this._done) return;
    this._done = true;

    this.style.cssText = "display:block;width:100%;height:100%;min-height:100vh;";

    const iframe = document.createElement("iframe");
    this._frame = iframe;
    iframe.title = "NSPanel Core";
    iframe.style.cssText = "border:0;width:100%;height:100%;min-height:100vh;display:block;";
    iframe.setAttribute("allowfullscreen", "");
    iframe.addEventListener("load", () => {
      try { this._pushToken(); } catch (e) {}
    });
    this.appendChild(iframe);
    /* P310 (the user's report — "THE APP DASHBOARD says Unauthorized"): NEVER
     * load the gated page without a credential. In the HA companion app the
     * webview has no session cookie on first use, and a tokenless load shows
     * a bare "Unauthorized". Wait for the live token and load with it; if it
     * never lands (no hass), fall back to the cookie path after a grace
     * period so cookie-carrying users still get the page. */
    iframe.src = "about:blank";
    this._startTokenPoll();
    if (this._liveToken) {
      this._loadWithToken(this._liveToken);
    } else {
      this._tokenWait = setTimeout(() => {
        if (!this._liveToken) iframe.src = "/nspanel_core/ui";
      }, 5000);
    }
  }

  _loadWithToken(t) {
    try {
      if (this._tokenWait) { clearTimeout(this._tokenWait); this._tokenWait = null; }
      const want = "/nspanel_core/ui?ha_token=" + encodeURIComponent(t);
      if (this._frame && this._frame.src !== want) this._frame.src = want;
    } catch (e) {}
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
