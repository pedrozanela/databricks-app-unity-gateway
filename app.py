"""Teste mínimo: Databricks App chamando o Unity Gateway via SP do App (M2M) e via OBO."""
import base64
import json
import os
import traceback

from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from openai import OpenAI

MODEL = os.environ.get("GATEWAY_MODEL", "system.ai.claude-haiku-5-5")

app = FastAPI()
w = WorkspaceClient()  # usa DATABRICKS_CLIENT_ID/SECRET injetados pelo Apps (SP do App)
HOST = w.config.host.rstrip("/")
BASE_URL = f"{HOST}/ai-gateway/mlflow/v1"


def sp_token() -> str:
    # authenticate() devolve {"Authorization": "Bearer <token>"} e renova o token sozinho
    return w.config.authenticate()["Authorization"].split(" ", 1)[1]


def token_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        c = json.loads(base64.urlsafe_b64decode(payload))
        return {k: c.get(k) for k in ("sub", "client_id", "scope", "aud", "exp")}
    except Exception:
        return {"note": "token não é JWT"}


def call_gateway(token: str, prompt: str, model: str) -> dict:
    client = OpenAI(api_key=token, base_url=BASE_URL)
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return {"ok": True, "answer": r.choices[0].message.content}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc(limit=2)}


@app.get("/api/sp")
def via_sp(prompt: str = "Diga olá em uma frase.", model: str = MODEL):
    token = sp_token()
    return {"mode": "SP (M2M)", "base_url": BASE_URL, "model": model,
            "env_DATABRICKS_HOST": os.environ.get("DATABRICKS_HOST"),
            "identity": w.current_user.me().user_name,
            "token": token_claims(token), **call_gateway(token, prompt, model)}


@app.get("/api/obo")
def via_obo(request: Request, prompt: str = "Diga olá em uma frase.", model: str = MODEL):
    token = request.headers.get("x-forwarded-access-token")
    if not token:
        return {"mode": "OBO", "ok": False,
                "error": "sem x-forwarded-access-token (user authorization desligado no App?)"}
    return {"mode": "OBO", "base_url": BASE_URL, "model": model,
            "identity": request.headers.get("x-forwarded-email"),
            "token": token_claims(token), **call_gateway(token, prompt, model)}


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html><head><meta charset="utf-8"><title>Unity Gateway via App</title>
<style>body{font-family:system-ui;max-width:900px;margin:40px auto;padding:0 16px}
button{padding:8px 16px;margin-right:8px;cursor:pointer}pre{background:#f4f4f4;padding:12px;white-space:pre-wrap}</style></head>
<body><h2>Unity Gateway chamado por um Databricks App</h2>
<p>Prompt: <input id="p" size="60" value="Diga olá em uma frase."></p>
<p>Model service: <input id="m" size="60" value="system.ai.claude-haiku-5-5"></p>
<button onclick="go('sp')">Chamar via SP (M2M)</button>
<button onclick="go('obo')">Chamar via OBO (usuário)</button>
<pre id="out">...</pre>
<script>async function go(m){out.textContent='chamando '+m+'...';
const r=await fetch('/api/'+m+'?prompt='+encodeURIComponent(p.value)+'&model='+encodeURIComponent(m.value));
out.textContent=JSON.stringify(await r.json(),null,2);}</script></body></html>"""
