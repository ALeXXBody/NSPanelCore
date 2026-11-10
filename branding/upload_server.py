#!/usr/bin/env python3
"""Temporary LAN image-upload server. Serves a simple upload page and saves
files into /home/truenas_admin/NSPanelCore/branding/uploads/."""
import os
import re
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

UPLOAD_DIR = "/home/truenas_admin/NSPanelCore/branding/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSPanel Core - artwork upload</title>
<style>
body{background:#0d1016;color:#e8edf2;font-family:sans-serif;display:flex;
min-height:100vh;align-items:center;justify-content:center;margin:0}
.card{background:#141922;border:1px solid #39c8e855;border-radius:16px;
padding:32px;max-width:420px;text-align:center}
h1{font-size:20px;font-weight:600}h1 span{color:#39c8e8}
p{color:#8c96a0;font-size:14px}
input[type=file]{margin:18px 0;color:#8c96a0}
button{background:#39c8e8;color:#0d1016;border:0;border-radius:8px;
padding:10px 22px;font-size:15px;font-weight:600;cursor:pointer}
</style></head><body><div class="card">
<h1>NSPanel <span>Core</span> - artwork upload</h1>
<p>Drop the logo / branding image here.<br>It goes straight to the NAS.</p>
<form method="POST" enctype="multipart/form-data">
<input type="file" name="file" accept="image/*" required>
<br><button type="submit">Upload</button>
</form></div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No file")
            return
        boundary = re.search(r"boundary=([^;]+)", ctype).group(1).encode()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        # Extract the first file part
        parts = body.split(b"--" + boundary)
        saved = []
        for part in parts:
            if b"filename=" not in part:
                continue
            header_end = part.find(b"\r\n\r\n")
            if header_end < 0:
                continue
            fname_m = re.search(rb'filename="([^"]*)"', part)
            fname = fname_m.group(1).decode(errors="replace") if fname_m else "upload.bin"
            fname = os.path.basename(fname) or "upload.bin"
            data = part[header_end + 4:]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            if not data:
                continue
            out = os.path.join(UPLOAD_DIR, fname)
            with open(out, "wb") as f:
                f.write(data)
            saved.append((out, len(data)))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if saved:
            listing = "<br>".join(f"{os.path.basename(p)} ({s} bytes)" for p, s in saved)
            self.wfile.write(f"<html><body style='background:#0d1016;color:#39c8e8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh'><div><h2>Uploaded ✓</h2><p style='color:#8c96a0'>{listing}</p><p style='color:#8c96a0'>You can close this page.</p></div></body></html>".encode())
            for p, s in saved:
                print(f"UPLOAD RECEIVED: {p} ({s} bytes)", flush=True)
        else:
            self.wfile.write(b"<html><body style='background:#0d1016;color:#f66'><h2>No file received</h2></body></html>")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = 8333
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Upload server listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()
