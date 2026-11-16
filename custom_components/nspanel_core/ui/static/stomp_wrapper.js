var stomp_subscription_callbacks = {};
var stomp_subscription_destinations = {};
var stomp_auth_failures = 0;
function stomp_connected_callback() {
  console.log("Connected to STOMP. Resubscribing...");
  stomp_auth_failures = 0;
  $("#ws_connection_in_progress_notification").addClass("hidden");

  // Resubscribe to all subscriptions
  for (const topic in stomp_subscription_destinations) {
    console.log("STOMP sub:", topic);
    var subscription = stomp_client.subscribe(topic, stomp_message_callback);
    stomp_subscription_destinations[topic] = subscription;
  }
}

function stomp_send(destination, message) {
  stomp_client.publish({
    destination: destination,
    headers: {
      "content-type": "text/plain",
    },
    body: message,
  });
}

function stomp_disconnected_callback() {
  console.log("Disconnected from STOMP.");
  $("#ws_connection_in_progress_notification").removeClass("hidden");
}

function stomp_websocket_close_callback() {
  console.log("Disconnected from STOMP (websocket closed).");
  // $("#ws_connection_in_progress_notification").removeClass("hidden");
}

function stomp_websocket_error_callback() {
  console.log("Disconnected from STOMP (websocket error).");
  $("#ws_connection_in_progress_notification").removeClass("hidden");
}

function stomp_error_callback(error) {
  var detail = "";
  try {
    if (error && typeof error.body === "string" && error.body) detail = error.body;
  } catch (e) {}
  if (!detail) {
    try {
      var bin = error && (error.binaryBody || error._binaryBody);
      if (bin && bin.length) detail = new TextDecoder().decode(bin);
    } catch (e2) {}
  }
  console.error("STOMP error:" + (detail ? " " + detail : ""));
  // Auth failures (expired/revoked token) would otherwise retry forever
  // with the same dead credentials: refresh once, then reconnect cleanly.
  // Without this the card sits on "Unknown state" indefinitely.
  var msg = (detail || "").toLowerCase();
  var auth = msg.indexOf("not authorized") !== -1 || msg.indexOf("missing or invalid access_token") !== -1 || msg.indexOf("unauthorized") !== -1;
  if (!auth) return;
  stomp_auth_failures += 1;
  if (stomp_auth_failures > 3) {
    console.error("STOMP auth failed repeatedly — stopping retries. Please log in to Home Assistant again.");
    try { stomp_client.deactivate(); } catch (e3) {}
    try { if (typeof nspanelShowLoginBanner === "function") nspanelShowLoginBanner(); } catch (e4) {}
    return;
  }
  try { stomp_client.deactivate(); } catch (e5) {}
  setTimeout(function () {
    var p = null;
    try { if (typeof nspanelRefreshTokenIfNeeded === "function") p = nspanelRefreshTokenIfNeeded(true); } catch (e6) {}
    Promise.resolve(p).catch(function () {}).then(function () {
      try { stomp_client.activate(); } catch (e7) {}
    });
  }, 1500);
}

function stomp_subscribe(topic, callback) {
  if (stomp_subscription_callbacks[topic]) {
    if (!stomp_subscription_callbacks[topic]["callbacks"].includes(callback)) {
      console.log("Attaching callback to existing subscription");
      stomp_subscription_callbacks[topic]["callbacks"].push(callback);
    }
  } else {
    stomp_subscription_callbacks[topic] = {
      subscription: null,
      callbacks: [callback],
    };
  }

  // Try subscribing if not already subscribed.
  if (!stomp_subscription_destinations[topic]) {
    stomp_subscription_destinations[topic] = null;

    // If the subscribe fails, log the error but it's still in the list of subscriptions though null.
    // It will most probaby fail because there is no STOMP connection. When a connection is established,
    // the subscription will be retried.
    try {
      var subscription = stomp_client.subscribe(topic, stomp_message_callback);
      stomp_subscription_destinations[topic] = subscription;
    } catch (error) {
      // console.error("STOMP subscription error:", error);
    }
  }
}

function stomp_unsubscribe(topic, callback) {
  stomp_subscription_callbacks[topic]["callbacks"].splice(stomp_subscription_callbacks[topic]["callbacks"].indexOf(callback), 1);

  if (stomp_subscription_callbacks[topic]["callbacks"].length === 0) {
    stomp_subscription_destinations[topic].unsubscribe();
    delete stomp_subscription_callbacks[topic];
    delete stomp_subscription_destinations[topic];
  }
}

function stomp_message_callback(message) {
  stomp_subscription_callbacks[message.headers.destination]["callbacks"].forEach(function (callback) {
    callback(message);
  });
}

function stomp_reconnect_callback() {
  // No username or password required to connect to STOMP websocket. Set dummy values.
  // Refresh the token on every (re)connect — it may have rotated.
  stomp_client.connectHeaders["access_token"] = nspanelStompToken();
  stomp_client.connect("user", "pass", stomp_connected_callback, stomp_disconnected_callback, stomp_error_callback);
}

function nspanelStompToken() {
  if (typeof nspanelGetToken === "function") {
    try {
      var t = nspanelGetToken();
      if (t) return t;
    } catch (e) {}
  }
  return "";
}

// Setup base Stomp connection so that all other components can it use
var stomp_websocket_address = "";
if (location.protocol === "https:") {
  stomp_websocket_address = "wss://";
} else {
  stomp_websocket_address = "ws://";
}

// Behind a reverse proxy / Nabu Casa the port is empty (default 443/80);
// appending a bare ":" produces an invalid URL and the UI never connects.
stomp_websocket_address += location.hostname + (location.port ? ":" + location.port : "") + "/nspanel_core/ws";
const stomp_client = new StompJs.Client({
  brokerURL: stomp_websocket_address,
  connectHeaders: {
    login: "user",
    passcode: "pass",
    "access_token": nspanelStompToken(),
  },
  reconnectDelay: 2500,
  heartbeatIncoming: 1000,
  heartbeatOutgoing: 1000,
  debug: function (str) {}, // Disable debug logging
});

stomp_client.onConnect = stomp_connected_callback;
stomp_client.onDisconnect = stomp_disconnected_callback;
stomp_client.onWebSocketClose = stomp_websocket_close_callback;
stomp_client.onWebSocketError = stomp_websocket_error_callback;
stomp_client.onStompError = stomp_error_callback;
stomp_client.beforeConnect = function () {
  // Re-read the token on EVERY (re)connect — the header captured at load
  // goes stale (30-min expiry) and retrying with it loops on ERROR forever.
  try { stomp_client.connectHeaders["access_token"] = nspanelStompToken(); } catch (e) {}
};
stomp_client.stompVersions = new StompJs.Versions([]); // Set empty versions as to not set the "Sec-WebSocket-Protocol" header as that causes chrome to fail to connect.

$(document).ready(() => {
  // Only connect once the whole document has loaded and all callbacks has been registered
  stomp_client.activate();
});
