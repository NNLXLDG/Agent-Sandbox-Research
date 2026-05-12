import requests
import time

from .config import AGENT_BASE_URL, AGENT_API_TOKEN, AGENT_MESSAGE_ENDPOINT, API_TIMEOUT


class AgentClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {AGENT_API_TOKEN}",
            "Content-Type": "application/json",
        })

    def send_message(self, payload: str) -> dict:
        url = f"{AGENT_BASE_URL}{AGENT_MESSAGE_ENDPOINT}"
        started = time.time()

        try:
            resp = self.session.post(
                url,
                json={"message": payload},
                timeout=API_TIMEOUT,
            )
            elapsed = round(time.time() - started, 2)

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    body = {"raw_text": resp.text}
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "response": body,
                    "response_text": self._extract_text(body),
                    "elapsed": elapsed,
                }
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": resp.text[:500],
                    "elapsed": elapsed,
                }

        except requests.Timeout:
            return {
                "success": False,
                "status_code": None,
                "error": f"Request timed out after {API_TIMEOUT}s",
                "elapsed": round(time.time() - started, 2),
            }
        except requests.ConnectionError as e:
            return {
                "success": False,
                "status_code": None,
                "error": f"Connection error: {e}",
                "elapsed": round(time.time() - started, 2),
            }
        except Exception as e:
            return {
                "success": False,
                "status_code": None,
                "error": str(e),
                "elapsed": round(time.time() - started, 2),
            }

    def _extract_text(self, body: dict) -> str:
        if "response" in body:
            r = body["response"]
            if isinstance(r, str):
                return r
            if isinstance(r, dict):
                return r.get("text", r.get("content", str(r)))
            return str(r)
        if "text" in body:
            return body["text"]
        if "content" in body:
            return body["content"]
        if "message" in body:
            m = body["message"]
            return m if isinstance(m, str) else m.get("content", str(m))
        return str(body)
