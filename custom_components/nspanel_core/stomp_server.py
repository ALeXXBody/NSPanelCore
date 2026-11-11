"""STOMP-over-WebSocket server — Python port of the C++ WebsocketServer.

Serves the original manager UI's live updates: topic registry with retained
values, last-will on disconnect, SEND routing to per-topic callbacks.
Runs on its own asyncio WebSocket endpoint served by aiohttp.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any, Callable

from aiohttp import web, WSMsgType

_LOGGER = logging.getLogger(__name__)

FRAME_COMMANDS = {
    "CONNECT", "DISCONNECT", "SEND", "SUBSCRIBE", "UNSUBSCRIBE",
    "ACK", "NACK", "CONNECTED", "MESSAGE", "RECEIPT", "ERROR",
}


def decode_frame(data: str):
    headers: dict[str, str] = {}
    command = None
    lines = data.split("\n")
    i = 0
    for i, line in enumerate(lines):
        line = line.rstrip("\r")
        if line == "":
            i += 1
            break
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.replace("\\r", "\r").replace("\\n", "\n").replace("\\c", ":").replace("\\\\", "\\")
            headers.setdefault(key, value)  # first header wins (STOMP 1.2)
        elif line in FRAME_COMMANDS:
            command = line
    body = "\n".join(lines[i:])
    if "content-length" in headers:
        n = int(headers["content-length"])
        body = body[:n]
    elif "\x00" in body:
        body = body[: body.index("\x00")]
    return command, headers, body


def encode_frame(command: str, headers: dict[str, str], body: str) -> str:
    out = [command + "\n"]
    for k, v in headers.items():
        v = v.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace(":", "\\c")
        out.append(f"{k}:{v}\n")
    out.append("\n")
    out.append(body)
    out.append("\x00")
    return "".join(out)


class StompConnection:
    def __init__(self, ws: web.WebSocketResponse) -> None:
        self.ws = ws
        self.subscriptions: dict[str, str] = {}  # topic -> subscription id
        self.last_will: dict | None = None
        self.lock = asyncio.Lock()

    async def send(self, command: str, headers: dict[str, str], body: str) -> None:
        async with self.lock:
            await self.ws.send_str(encode_frame(command, headers, body))


class StompServer:
    """Topic registry + connections. Mirror MQTT publishes via mirror()."""

    def __init__(self) -> None:
        self.topics: dict[str, dict] = {}  # topic -> {retained, value, subscribers: {conn: sub_id}}
        self.connections: set[StompConnection] = set()
        self.send_callbacks: dict[str, Callable] = {}
        self.global_callbacks: list[Callable] = []

    # -- public API used by the manager ---------------------------------

    def has_subscribers(self) -> bool:
        return bool(self.connections)

    def set_retained(self, topic: str, retained: bool) -> None:
        self._topic(topic)["retained"] = retained

    def update_topic(self, topic: str, value: str, retain_override: bool | None = None) -> None:
        t = self._topic(topic)
        if retain_override is not None:
            t["retained"] = retain_override
        if t["retained"]:
            t["value"] = value
            t["has_value"] = True
        if t["subscribers"]:
            asyncio.create_task(self._fanout(t, value))

    def mirror_mqtt(self, topic: str, payload: str | bytes, retain: bool) -> None:
        """Mirror an MQTT publish to 'mqtt/<topic>' — base64 payload, exactly
        like the C++ bridge."""
        if not self.has_subscribers():
            return
        if isinstance(payload, bytes):
            encoded = base64.b64encode(payload).decode("ascii")
        else:
            encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
        stomp_topic = f"mqtt/{topic}"
        self.set_retained(stomp_topic, retain)
        self.update_topic(stomp_topic, encoded)

    def attach_callback(self, topic: str, cb: Callable) -> None:
        self.send_callbacks[topic] = cb

    def attach_global_callback(self, cb: Callable) -> None:
        self.global_callbacks.append(cb)

    # -- internals -------------------------------------------------------

    def _topic(self, name: str) -> dict:
        t = self.topics.get(name)
        if t is None:
            t = {"retained": False, "value": "", "has_value": False, "subscribers": {}}
            self.topics[name] = t
        return t

    async def _fanout(self, t: dict, value: str) -> None:
        for conn, sub_id in list(t["subscribers"].items()):
            await conn.send("MESSAGE", {
                "message-id": str(uuid.uuid4()),
                "content-type": "text/plain",
                "destination": t["name"],
                "subscription": sub_id,
            }, value)

    def _snapshot_subscribers(self, t: dict) -> dict:
        return dict(t["subscribers"])

    def _subscribe(self, conn: StompConnection, topic: str, sub_id: str) -> None:
        t = self._topic(topic)
        t["subscribers"][conn] = sub_id
        if t["has_value"] and t["value"] != "":
            asyncio.create_task(conn.send("MESSAGE", {
                "message-id": str(uuid.uuid4()),
                "content-type": "text/plain",
                "destination": topic,
                "subscription": sub_id,
            }, t["value"]))

    def _unsubscribe(self, conn: StompConnection, topic: str | None, sub_id: str | None) -> None:
        for name, t in self.topics.items():
            if topic is not None and name != topic:
                continue
            for c, sid in list(t["subscribers"].items()):
                if c is conn and (sid == sub_id or sub_id is None):
                    del t["subscribers"][c]

    def _fire_last_will(self, conn: StompConnection) -> None:
        lw = conn.last_will
        if not lw or not lw.get("topic"):
            return
        topic, message = lw["topic"], lw["message"]
        self.set_retained(topic, lw.get("retained", False))
        self.update_topic(topic, message)
        frame = {"destination": topic, "body": message}
        for cb in self.global_callbacks:
            cb(frame)
        cb = self.send_callbacks.get(topic)
        if cb:
            cb(frame)

    # -- websocket handling ----------------------------------------------

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        conn = StompConnection(ws)
        self.connections.add(conn)
        _LOGGER.info("STOMP client connected: %s", request.remote)
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                if msg.data == "\n":  # heartbeat
                    continue
                command, headers, body = decode_frame(msg.data)
                await self._handle_frame(conn, command, headers, body)
        finally:
            self.connections.discard(conn)
            self._unsubscribe(conn, None, None)
            self._fire_last_will(conn)
            _LOGGER.info("STOMP client disconnected: %s", request.remote)
        return ws

    async def _handle_frame(self, conn: StompConnection, command: str | None,
                            headers: dict[str, str], body: str) -> None:
        if command is None:
            _LOGGER.error("Failed to parse STOMP frame")
            return

        if command == "CONNECT":
            accept_version = headers.get("accept-version", "")
            versions = [v.strip() for v in accept_version.split(",") if v.strip()]
            if accept_version == "" or "1.2" in versions:
                connected_headers = {
                    "version": "1.2",
                    "session": str(uuid.uuid4()),
                    "server": "NSPanelManager",
                }
                hb = headers.get("heart-beat", "0,0")
                if hb.split(",")[0] != "0":
                    connected_headers["heart-beat"] = "0,1000"
                await conn.send("CONNECTED", connected_headers, "")
                topic = headers.get("last_will_topic", "")
                if topic:
                    conn.last_will = {
                        "topic": topic,
                        "message": headers.get("last_will_message", ""),
                        "retained": headers.get("last_will_retained", "").lower() == "true",
                    }
                    _LOGGER.info("Client last will: '%s' retained? %s", topic, conn.last_will["retained"])
            else:
                await conn.send("ERROR", {"version": "1.2"}, "Supported protocol versions are 1.2")

        elif command == "SUBSCRIBE":
            destination = headers.get("destination", "")
            sub_id = headers.get("id", "")
            if not destination or not sub_id:
                return
            _LOGGER.debug("STOMP subscribing to topic %s (id: %s)", destination, sub_id)
            self._subscribe(conn, destination, sub_id)

        elif command == "UNSUBSCRIBE":
            self._unsubscribe(conn, headers.get("destination"), headers.get("id"))

        elif command == "SEND":
            destination = headers.get("destination", "")
            for cb in self.global_callbacks:
                cb({"destination": destination, "body": body})
            cb = self.send_callbacks.get(destination)
            if cb:
                cb({"destination": destination, "body": body})
            elif not destination.startswith("mqtt/"):
                _LOGGER.warning("Received STOMP SEND for unknown topic: %s", destination)

        elif command == "DISCONNECT":
            await conn.ws.close()
