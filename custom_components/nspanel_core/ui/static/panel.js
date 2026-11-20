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
  _extractToken(h) {
    try {
      if (!h || !h.auth) return "";
      const a = h.auth;
      return (a.data && a.data.access_token) ||
             (typeof a.accessToken === "string" ? a.accessToken : "") ||
             (a.tokens && a.tokens.access_token) || "";
    } catch (e) { return ""; }
  }

  async _refreshTokenFromHass(h) {
    try {
      const a = h && h.auth;
      if (!a) return "";
      let t = this._extractToken(h);
      if (t) return t;
      if (typeof a.getAccessToken === "function") {
        try { t = await a.getAccessToken(); } catch (e1) {}
      }
      if (!t && typeof a.refreshAccessToken === "function") {
        try { await a.refreshAccessToken(); } catch (e2) {}
        t = (a.data && a.data.access_token) ||
            (typeof a.accessToken === "string" ? a.accessToken : "") ||
            (a.tokens && a.tokens.access_token) || "";
      }
      return (typeof t === "string" ? t : "") || "";
    } catch (e) { return ""; }
  }

  _applyToken(t) {
    if (!t || t === this._liveToken) return;
    this._liveToken = t;
    this._pushToken();
    try {
      document.cookie = "nspanel_token=" + encodeURIComponent(t) +
        "; path=/; max-age=3600; SameSite=Strict";
    } catch (e) {}
    this._exchangeSession(t);
    if (this._frame) {
      const want = "/nspanel_core/ui?ha_token=" + encodeURIComponent(t);
      try {
        const cur = this._frame.src || "";
        if (cur.indexOf("ha_token=") === -1 ||
            decodeURIComponent((cur.split("ha_token=")[1] || "").split("&")[0]) !== t) {
          this._frame.src = want;
        }
      } catch (e2) { this._frame.src = want; }
    }
  }

  set hass(h) {
    try {
      this._hassRef = h;  // P311: the poll re-reads the LIVE auth later
      const t = this._extractToken(h);
      if (t) {
        this._applyToken(t);
      } else if (h && h.auth && !this._tokenFetchInFlight) {
        this._tokenFetchInFlight = true;
        this._refreshTokenFromHass(h).then((tok) => {
          this._tokenFetchInFlight = false;
          if (tok) this._applyToken(tok);
        }).catch(() => { this._tokenFetchInFlight = false; });
      }
    } catch (e) {}
  }

  connectedCallback() {
    if (this._done) return;
    this._done = true;

    this.style.cssText = "display:block;width:100%;height:100%;min-height:100vh;";

    const iframe = document.createElement("iframe");
    /* P311: WITHOUT embed_iframe, HA assigns the LIVE hass to THIS element
     * (its own contract — verified in the frontend bundle:
     *   d(s, {panel, hass: this.hass, narrow, route})).
     * The token is therefore guaranteed in the app and in the browser —
     * never load the gated page before it arrives; `set hass` points the
     * iframe. The 10 s fallback covers a hass that never lands. */
    iframe.src = this._liveToken
      ? "/nspanel_core/ui?ha_token=" + encodeURIComponent(this._liveToken)
      : "about:blank";
    iframe.title = "NSPanel Core";
    iframe.style.cssText = "border:0;width:100%;height:100%;min-height:100vh;display:block;";
    iframe.setAttribute("allowfullscreen", "");
    this._frame = iframe;
    iframe.addEventListener("load", () => {
      try { this._pushToken(); } catch (e) {}
    });
    this.appendChild(iframe);
    /* P311: the app delivers its token LATE. Keep reading the LIVE hass
     * and try async refresh/getAccessToken until we have a token. The
     * public shell still loads immediately and can self-authenticate. */
    this._pollStart = Date.now();
    this._tokenPoll = setInterval(() => {
      try {
        const h = this._hassRef;
        const t = this._extractToken(h);
        if (t) {
          this._applyToken(t);
          clearInterval(this._tokenPoll);
          return;
        }
        if (h && h.auth && !this._tokenFetchInFlight) {
          this._tokenFetchInFlight = true;
          this._refreshTokenFromHass(h).then((tok) => {
            this._tokenFetchInFlight = false;
            if (tok) this._applyToken(tok);
          }).catch(() => { this._tokenFetchInFlight = false; });
        }
        if (Date.now() - this._pollStart > 120000) clearInterval(this._tokenPoll);
      } catch (e) {}
    }, 1500);
    if (!this._liveToken) {
      // the shell is PUBLIC and self-authenticates (the bridges) — a
      // tokenless load is no longer a dead end
      iframe.src = "/nspanel_core/ui";
    }
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
