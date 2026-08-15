"""Thin wrapper around the Mist API: auth, base URL, and a name-based
get-or-create/update helper that makes push.py idempotent.
"""
import os
import sys
import requests
from dotenv import load_dotenv

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(_ENV_PATH)


class MistClient:
    def __init__(self):
        self.token = os.environ.get("MIST_API_TOKEN")
        self.base_url = os.environ.get("MIST_BASE_URL", "https://api.mist.com").rstrip("/")
        self.org_id = os.environ.get("MIST_ORG_ID")
        if not self.token or not self.org_id:
            sys.exit("MIST_API_TOKEN and MIST_ORG_ID must be set in .env")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
        })

    def _url(self, path):
        return f"{self.base_url}{path}"

    def get(self, path):
        r = self.session.get(self._url(path), timeout=20)
        r.raise_for_status()
        return r.json()

    def post(self, path, body):
        r = self.session.post(self._url(path), json=body, timeout=20)
        if not r.ok:
            sys.exit(f"POST {path} failed [{r.status_code}]: {r.text}")
        return r.json()

    def put(self, path, body):
        r = self.session.put(self._url(path), json=body, timeout=20)
        if not r.ok:
            sys.exit(f"PUT {path} failed [{r.status_code}]: {r.text}")
        return r.json()

    def delete(self, path):
        r = self.session.delete(self._url(path), timeout=20)
        if r.status_code not in (200, 204, 404):
            sys.exit(f"DELETE {path} failed [{r.status_code}]: {r.text}")

    def org_path(self, suffix):
        return f"/api/v1/orgs/{self.org_id}{suffix}"

    def upsert_by_name(self, list_path, name, body, item_base_path=None):
        """Create-or-update an org object matched by its `name` field.
        Returns (id, action) where action is 'created' or 'updated'.

        `item_base_path` overrides where the individual PUT goes — needed for
        sites, whose single-object CRUD lives at /api/v1/sites/{id} rather
        than under /api/v1/orgs/{org}/sites/{id} like every other object type.
        """
        item_base_path = item_base_path or list_path
        existing = self.get(list_path)
        match = next((o for o in existing if o.get("name") == name), None)
        if match:
            self.put(f"{item_base_path}/{match['id']}", body)
            return match["id"], "updated"
        created = self.post(list_path, body)
        return created["id"], "created"
