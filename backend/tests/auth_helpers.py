"""Clients authenticate through the real cookie API; no application auth overrides."""
from http.cookies import SimpleCookie

from fastapi.testclient import TestClient


def cookie_headers(client, company_id=None):
    values = {cookie.name: cookie.value for cookie in client.cookies.jar}
    csrf = values.get("agentconnect_csrf", values.get("__Host-agentconnect_csrf", ""))
    headers = {"Cookie": "; ".join(f"{key}={value}" for key, value in values.items()), "X-CSRF-Token": csrf}
    if company_id is not None:
        headers["X-Company-ID"] = str(company_id)
    return headers


class CookieClient(TestClient):
    def request(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and str(url).startswith("/api"):
            if "Cookie" in headers:
                cookies = SimpleCookie(); cookies.load(headers["Cookie"])
                token = cookies.get("agentconnect_csrf") or cookies.get("__Host-agentconnect_csrf")
                if token:
                    headers.setdefault("X-CSRF-Token", token.value)
            else:
                token = self.cookies.get("agentconnect_csrf") or self.cookies.get("__Host-agentconnect_csrf")
                if token is None:
                    token = super().request("GET", "/api/v1/auth/csrf").json()["csrf_token"]
                headers.setdefault("X-CSRF-Token", token)
        return super().request(method, url, headers=headers, **kwargs)


class LegacyClient(CookieClient):
    def __enter__(self):
        super().__enter__()
        payload = {"name": "Demo owner", "company_name": "Demo workspace", "email": "demo-owner@example.test", "password": "test-only-demo-password"}
        response = self.post("/api/v1/auth/register", json=payload)
        if response.status_code == 409:
            response = self.post("/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]})
        assert response.status_code in (200, 201), response.text
        if not self.get("/api/v1/legacy/agents").json():
            from app.db.seed import SEED_AGENTS
            for definition in SEED_AGENTS:
                row = {key: value for key, value in definition.items() if key != "interests"}
                row["interests"] = [{"interest_type": kind, "value": value, "weight": weight} for kind, value, weight in definition["interests"]]
                result = self.post("/api/v1/legacy/agents", json=row)
                assert result.status_code == 201, result.text
        return self

    def request(self, method, url, **kwargs):
        url = str(url)
        if url.startswith("/api/agents"):
            url = url.replace("/api/agents", "/api/legacy/agents", 1)
        return super().request(method, url, **kwargs)
