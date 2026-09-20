#!/usr/bin/env python3
"""End-to-end check of Drive: OIDC login, upload, download, and a real editing session.

    DOMAIN=example.org E2E_USER=someone E2E_PASSWORD=... ./e2e.py

It drives the real authorization-code flow (the client has no password grant), uploads
through the presigned URL the way a browser does, reads the file back through the media
proxy, and opens the Collabora websocket — which is the only check that catches Envoy
normalising the path Collabora encodes its session into.

It creates one file and deletes it. Run it after any change to the Gateway, the object
store route, or either application's release.
"""
import html
import os
import pathlib
import re
import sys
import uuid

import requests
from urllib.parse import quote, unquote

DOMAIN = os.environ.get("DOMAIN") or sys.exit("DOMAIN is required: the cluster's public DNS suffix")
DRIVE = f"https://drive.{DOMAIN}"
USER = os.environ["E2E_USER"]
PASSWORD = os.environ["E2E_PASSWORD"]

ok = True


def check(name, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'ok  ' if condition else 'FAIL'} {name}{('  — ' + str(detail)[:150]) if detail else ''}")


def login(user, password):
    s = requests.Session()
    s.headers["User-Agent"] = "office-platform-e2e"
    r = s.get(f"{DRIVE}/api/v1.0/authenticate/", timeout=30)
    m = re.search(r'<form[^>]+action="([^"]+)"', r.text)
    if not m:
        raise SystemExit(f"no Keycloak login form at {r.url} ({r.status_code})")
    s.post(html.unescape(m.group(1)), data={"username": user, "password": password}, timeout=30)
    s.headers["Referer"] = DRIVE
    if s.cookies.get("csrftoken"):
        s.headers["X-CSRFToken"] = s.cookies["csrftoken"]
    return s


print("== login ==")
s = login(USER, PASSWORD)
me = s.get(f"{DRIVE}/api/v1.0/users/me/", timeout=30)
check("OIDC authorization-code login", me.status_code == 200, me.status_code)
if me.status_code != 200:
    sys.exit(1)
print(f"       {me.json().get('email')}")

# --- upload -----------------------------------------------------------------
print("\n== upload (browser presigns straight to the object store) ==")
name = f"e2e-{uuid.uuid4().hex[:8]}.odt"
body = (pathlib.Path(__file__).parent / "sample.odt").read_bytes()

r = s.post(f"{DRIVE}/api/v1.0/items/", json={"title": name, "filename": name, "type": "file", "size": len(body)}, timeout=30)
check("create item", r.status_code in (200, 201), f"{r.status_code} {r.text[:150]}")
if r.status_code not in (200, 201):
    sys.exit(1)
item = r.json()
policy = item.get("upload_policy") or item.get("policy")
check("upload policy returned", bool(policy))
check("signed against the PUBLIC endpoint", policy and policy.startswith(f"https://s3.{DOMAIN}/drive/"), (policy or "")[:70])

# A browser sends Content-Type from the File object. Garage only returns ContentType on
# HEAD if it was set on PUT, and Drive reads head_response["ContentType"] unguarded, so
# omitting it here 500s upload-ended — an upstream bug that AWS S3 masks.
up = requests.put(policy, data=body, headers={"x-amz-acl": "private",
                  "Content-Type": "application/vnd.oasis.opendocument.text"}, timeout=120)
check("PUT from outside the cluster", up.status_code == 200, up.status_code)

pre = requests.options(policy, headers={"Origin": DRIVE, "Access-Control-Request-Method": "PUT"}, timeout=30)
check("CORS allows Drive's origin", pre.headers.get("access-control-allow-origin") == DRIVE, pre.headers.get("access-control-allow-origin"))
bad = requests.options(policy, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PUT"}, timeout=30)
check("CORS denies another origin", not bad.headers.get("access-control-allow-origin"), bad.headers.get("access-control-allow-origin"))

r = s.post(f"{DRIVE}/api/v1.0/items/{item['id']}/upload-ended/", json={}, timeout=30)
check("upload-ended accepted", r.status_code in (200, 201, 202, 204), f"{r.status_code} {r.text[:120]}")

# --- read it back -----------------------------------------------------------
print("\n== download (media proxy + auth subrequest) ==")
d = s.get(f"{DRIVE}/api/v1.0/items/{item['id']}/", timeout=30)
detail = d.json()
check("item ready", detail.get("upload_state") == "ready", detail.get("upload_state"))
check("mimetype detected", detail.get("mimetype") == "application/vnd.oasis.opendocument.text", detail.get("mimetype"))

url = detail["url"]
dl = s.get(url, timeout=60)
check("download returns the bytes", dl.status_code == 200 and dl.content == body, f"{dl.status_code}, {len(dl.content)}/{len(body)} bytes")
check("Content-Security-Policy set", dl.headers.get("Content-Security-Policy") == "default-src 'none'", dl.headers.get("Content-Security-Policy"))
check("served as an attachment", (dl.headers.get("Content-Disposition") or "").startswith("attachment"), dl.headers.get("Content-Disposition"))
anon = requests.get(url, timeout=30)
check("anonymous download denied", anon.status_code in (401, 403), anon.status_code)

# --- Collabora --------------------------------------------------------------
print("\n== Collabora ==")
check("Drive reports WOPI support for .odt", detail.get("is_wopi_supported") is True, detail.get("is_wopi_supported"))
w = s.get(f"{DRIVE}/api/v1.0/items/{item['id']}/wopi/", timeout=30)
check("WOPI session opens", w.status_code == 200, f"{w.status_code} {w.text[:150]}")
if w.status_code == 200:
    wj = w.json()
    launch = wj["launch_url"]
    check("editor served from our Collabora", f"collabora.{DOMAIN}" in launch, launch[:100])
    check("WOPISrc points back at Drive", f"drive.{DOMAIN}" in launch, "")
    check("access token issued", bool(wj.get("access_token")), f"ttl={wj.get('access_token_ttl')}")

    e = requests.get(launch, timeout=60)
    check("Collabora editor page loads", e.status_code == 200, e.status_code)

    # Collabora fetches this from outside the cluster with the token Drive minted.
    src = re.search(r"WOPISrc=([^&]+)", launch)
    check("launch URL carries a WOPISrc", bool(src), launch[:100])
    if src:
        info = requests.get(f"{unquote(src.group(1))}?access_token={wj['access_token']}", timeout=30)
        check("CheckFileInfo answers Collabora", info.status_code == 200, info.status_code)
        if info.status_code == 200:
            j = info.json()
            check("file is editable in the editor", j.get("UserCanWrite") is True, f"{j.get('BaseFileName')}, size={j.get('Size')}")
            fc = requests.get(f"{unquote(src.group(1))}/contents?access_token={wj['access_token']}", timeout=60)
            check("editor can fetch the file contents", fc.status_code == 200 and fc.content == body, f"{fc.status_code}, {len(fc.content)} bytes")

# --- the editing session itself ---------------------------------------------
# Collabora puts the WOPI source, percent-encoded, INSIDE the websocket path. Envoy
# must not normalise it; if it does, this 307s instead of upgrading.
if w.status_code == 200 and src:
    import base64, socket, ssl, time
    inner = quote(unquote(src.group(1)) + "?access_token=" + wj["access_token"], safe="")
    host = f"collabora.{DOMAIN}"
    line, first = "", b""
    for attempt in range(12):
        req = (f"GET /cool/{inner}/ws?compat=/ws HTTP/1.1\r\nHost: {host}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: https://{host}\r\n\r\n")
        with ssl.create_default_context().wrap_socket(
                socket.create_connection((host, 443), timeout=25), server_hostname=host) as c:
            c.sendall(req.encode())
            resp = c.recv(8192).decode("latin1", "replace")
            line = resp.split("\r\n")[0]
            if "101" in line:
                # Collabora streams progress frames as it loads the document; `ready` and
                # the permission frame arrive a beat after `connect`/`find`.
                c.settimeout(30)
                deadline = time.time() + 45
                while time.time() < deadline and not (b"ready" in first and b"perm:" in first):
                    try:
                        chunk = c.recv(8192)
                    except Exception:
                        break
                    if not chunk:
                        break
                    first += chunk
                break
        time.sleep(10)
    check("editing websocket upgrades", "101" in line, line)
    check("document loads in the editor", b'"id":"ready"' in first and b"perm: edit" in first,
          b" ".join(first.split())[:110])

print("\n== the edge still denies Collabora's admin surfaces ==")
for p in ("/browser/dist/admin/admin.html", "/browser/dist%2Fadmin/admin.html",
          "/cool/getMetrics", "/cool%2FgetMetrics"):
    code = requests.get(f"https://collabora.{DOMAIN}{p}", timeout=20).status_code
    check(f"blocked {p}", code in (400, 403), code)

# --- clean up ---------------------------------------------------------------
r = s.delete(f"{DRIVE}/api/v1.0/items/{item['id']}/", timeout=30)
print(f"\n       cleanup: {r.status_code}")
print("\nOK" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
