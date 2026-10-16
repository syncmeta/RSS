#!/usr/bin/env python3
"""RSSBox adapter for official Sign in with ChatGPT and Responses API.

Run login on the user's computer. Transfer the private credential file via
SSH to the self-hosted runtime. Never reuse browser cookies or Codex tokens.
"""
import argparse
import base64
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import time
import threading
from urllib.parse import parse_qs, urlencode, urlparse
import uuid

import jwt
import requests

AUTH = "https://auth.openai.com/api/accounts/authorize"
TOKEN = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
MODEL = "gpt-6-luna"


def save_private(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    with os.fdopen(os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def validate_identity(id_token, client_id, nonce):
    key = jwt.PyJWKClient("https://auth.openai.com/.well-known/jwks.json").get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, key.key, algorithms=["RS256"],
                        audience=client_id, issuer="https://auth.openai.com",
                        options={"require": ["exp", "iss", "aud", "sub", "nonce"]})
    if not secrets.compare_digest(claims["nonce"], nonce):
        raise RuntimeError("OIDC nonce mismatch")
    return claims


def credential_record(tokens, client_id, host_id, claims):
    scopes = tokens.get("scope", "").split()
    if PLAN_SCOPE not in scopes:
        raise RuntimeError("ChatGPT plan usage permission was not granted")
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise RuntimeError("Renewable credentials were not returned")
    return {**tokens, "client_id": client_id, "ext_agent_host_id": host_id,
            "subject": claims["sub"], "email": claims.get("email"),
            "issuer": claims["iss"], "scopes": scopes,
            "expires_at": time.time() + tokens["expires_in"]}


def login(path, port):
    path = Path(path)
    host_file = path.with_name("host.json")
    if not host_file.exists():
        save_private(host_file, {"ext_agent_host_id": "urn:uuid:" + str(uuid.uuid4())})
    host_id = json.loads(host_file.read_text())["ext_agent_host_id"]
    saved = json.loads(path.read_text()) if path.exists() else None
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    redirect = f"http://127.0.0.1:{port}/auth/callback"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": saved["client_id"] if saved else "dynamic_agent_client",
              "ext_agent_host_id": host_id, "response_type": "code", "redirect_uri": redirect,
              "scope": "openid profile email offline_access resource.invoke " + PLAN_SCOPE,
              "resource": RESOURCE, "state": state, "nonce": nonce,
              "code_challenge_method": "S256", "code_challenge": challenge}
    if saved:
        params["id_token_hint"] = saved["id_token"]
    else:
        params["agent_name_hint"] = "RSSBox Translation"
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Callback query contains a one-time authorization code.

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            if not secrets.compare_digest(query.get("state", [""])[0], state):
                self.send_error(400, "Invalid state")
                return
            try:
                if "error" in query:
                    raise RuntimeError("Authorization declined")
                issued = query.get("client_id", [saved["client_id"] if saved else ""])[0]
                if not issued or issued == "dynamic_agent_client" or (saved and issued != saved["client_id"]):
                    raise RuntimeError("Invalid issued client ID")
                response = requests.post(TOKEN, data={"grant_type": "authorization_code", "client_id": issued,
                    "code": query["code"][0], "code_verifier": verifier,
                    "redirect_uri": redirect, "resource": RESOURCE}, timeout=(15, 60))
                response.raise_for_status()
                tokens = response.json()
                claims = validate_identity(tokens["id_token"], issued, nonce)
                if saved and claims["sub"] != saved["subject"]:
                    raise RuntimeError("Account identity changed")
                save_private(path, credential_record(tokens, issued, host_id, claims))
                result["ok"] = True
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("ChatGPT 授权已保存，可以返回 Codex。".encode())
            except Exception as exc:
                result["error"] = type(exc).__name__
                self.send_error(400, "Authorization failed; return to Codex")

    server = HTTPServer(("127.0.0.1", port), Callback)
    server.timeout = 1
    print("AUTHORIZATION_URL=" + AUTH + "?" + urlencode(params), flush=True)
    deadline = time.time() + 1200
    while not result and time.time() < deadline:
        server.handle_request()
    server.server_close()
    if not result.get("ok"):
        raise RuntimeError("Authorization did not complete: " + result.get("error", "timeout"))
    print("Authorization saved; no credentials printed.", flush=True)


def access_token(path):
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(path.read_text())
        if PLAN_SCOPE not in record["scopes"]:
            raise RuntimeError("ChatGPT plan usage disabled")
        if record["expires_at"] < time.time() + 120:
            response = requests.post(TOKEN, data={"grant_type": "refresh_token",
                "client_id": record["client_id"], "refresh_token": record["refresh_token"],
                "resource": RESOURCE}, timeout=(15, 60))
            response.raise_for_status()
            replacement = response.json()
            if not replacement.get("refresh_token") or not replacement.get("access_token"):
                raise RuntimeError("Refresh did not return replacement credentials")
            scopes = replacement.get("scope", " ".join(record["scopes"])).split()
            if PLAN_SCOPE not in scopes:
                raise RuntimeError("ChatGPT plan usage revoked")
            record.update(replacement)
            record.update(scopes=scopes, expires_at=time.time() + replacement["expires_in"])
            save_private(path, record)
        return record["access_token"]


def request_body(messages, model=MODEL):
    if model != MODEL:
        raise ValueError("Only the requested Luna model is enabled")
    instructions, inputs = [], []
    for message in messages:
        role, content = message["role"], message["content"]
        if not isinstance(content, str):
            raise ValueError("This translation adapter accepts text only")
        if role in ("system", "developer"):
            instructions.append(content)
        elif role in ("user", "assistant"):
            inputs.append({"role": role, "content": content})
        else:
            raise ValueError("Unsupported message role")
    if not inputs:
        raise ValueError("Missing translation input")
    return {"model": model, "instructions": "\n\n".join(instructions),
            "input": inputs, "store": False, "stream": True,
            "reasoning": {"effort": "none"}}


def consume_events(lines, deadline=None):
    text, completed, usage = [], False, {}
    characters = 0
    for line in lines:
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError("Translation exceeded its completion deadline")
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        event = json.loads(payload)
        kind = event.get("type")
        if kind == "response.output_text.delta":
            characters += len(event["delta"])
            if characters > 8 * 1024 * 1024:
                raise RuntimeError("Translation exceeds adapter memory limit")
            text.append(event["delta"])
        elif kind == "response.completed":
            completed = True
            usage = event.get("response", {}).get("usage", {})
        elif kind in ("response.failed", "response.incomplete", "error"):
            raise RuntimeError("ChatGPT response failed or incomplete")
    content = "".join(text)
    if not completed or not content.strip():
        raise RuntimeError("No complete nonempty translation received")
    return content, usage


def translate(path, payload):
    body = request_body(payload["messages"], payload.get("model", MODEL))
    with requests.post(RESOURCE + "/responses", headers={"Authorization": "Bearer " + access_token(path)},
                       json=body, stream=True, timeout=(15, 60)) as response:
        response.raise_for_status()
        response.encoding = "utf-8"
        content, usage = consume_events(response.iter_lines(decode_unicode=True), time.monotonic() + 240)
    return {"id": "rss-plan-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
            "model": MODEL, "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": usage.get("input_tokens", 0),
                      "completion_tokens": usage.get("output_tokens", 0),
                      "total_tokens": usage.get("total_tokens", 0)}}


def serve(path, host, port):
    bridge_key = os.environ["RSS_PLAN_BRIDGE_KEY"]
    inference_lock = threading.Lock()
    class Adapter(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, value):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A timed-out caller must not receive a partial article.

        def do_GET(self):
            if self.path == "/healthz":
                self.reply(200, {"service": "rss-chatgpt-plan", "credentials_present": Path(path).exists()})
            else:
                self.reply(404, {"error": "not_found"})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.reply(404, {"error": "not_found"})
                return
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + bridge_key):
                self.reply(401, {"error": "unauthorized"})
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 8 * 1024 * 1024:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(size))
                with inference_lock:
                    result = translate(path, payload)
                self.reply(200, result)
            except (ValueError, KeyError):
                self.reply(400, {"error": "invalid_translation_request"})
            except Exception as exc:
                # Never return partial output, secrets, or upstream response bodies.
                self.reply(503, {"error": "chatgpt_plan_unavailable", "type": type(exc).__name__})
    # Health probes remain responsive while the single inference lane is busy.
    ThreadingHTTPServer((host, port), Adapter).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["login", "serve", "probe"])
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    if args.mode == "login":
        login(args.credentials, args.port or 1455)
    elif args.mode == "serve":
        serve(args.credentials, args.host, args.port or 8010)
    else:
        catalog = requests.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + access_token(args.credentials)}, timeout=(15, 60))
        catalog.raise_for_status()
        available = [model["slug"] for model in catalog.json()["models"] if model.get("visibility") == "list"]
        if MODEL not in available:
            raise RuntimeError("Requested Luna model is unavailable for the authorized account")
        result = translate(args.credentials, {"model": MODEL, "messages": [
            {"role": "system", "content": "Translate to Simplified Chinese; return only the translation."},
            {"role": "user", "content": "The RSS migration preserves all historical articles."}]})
        print("Completed ChatGPT plan inference with " + MODEL + ": " + result["choices"][0]["message"]["content"])
