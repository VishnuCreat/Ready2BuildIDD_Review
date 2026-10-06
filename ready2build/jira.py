import hashlib
import logging
import time
from urllib.parse import urlparse

import requests

from .models import Attachment, Issue

log = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, base_url, email, token, session=None, dim_field=""):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.dim_field = dim_field
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, method, url, **kwargs):
        for attempt in range(5):
            response = self.session.request(method, url, timeout=60, **kwargs)
            if response.status_code == 429 or response.status_code >= 500:
                wait = int(response.headers.get("Retry-After", min(2 ** attempt, 30)))
                if attempt < 4:
                    time.sleep(wait)
                    continue
            if response.status_code >= 400:
                log.error("Jira API request failed: status=%s endpoint=%s", response.status_code, urlparse(url).path)
                response.raise_for_status()
            return response

    def search_issues(self, jql):
        start, page_size, issues = 0, 100, []
        while True:
            fields_arg = "summary,status,attachment,labels,description,project" + (f",{self.dim_field}" if self.dim_field else "")
            data = self._request("GET", f"{self.base_url}/rest/api/3/search", params={"jql": jql, "startAt": start, "maxResults": page_size, "fields": fields_arg}).json()
            for raw in data.get("issues", []):
                fields = raw.get("fields", {})
                attachments = [Attachment(str(a["id"]), a["filename"], a["content"], a.get("mimeType", ""), a.get("size", 0)) for a in fields.get("attachment", [])]
                description = fields.get("description")
                text = str(description or "")
                digest = hashlib.sha256((text + "|" + "|".join(f"{a.id}:{a.filename}:{a.size}" for a in attachments)).encode()).hexdigest()
                project = raw.get("fields", {}).get("project", {}).get("key", "")
                issue_url = f"{self.base_url}/browse/{raw['key']}"
                dim = str(fields.get(self.dim_field) or "") if self.dim_field else ""
                dim = dim or self._find_dim(fields)
                issues.append(Issue(raw["key"], issue_url, dim, fields.get("summary", ""), fields.get("status", {}).get("name", ""), attachments, digest))
            start += len(data.get("issues", []))
            if not data.get("issues") or start >= data.get("total", 0):
                break
        return issues

    @staticmethod
    def _find_dim(fields):
        import re
        values = [fields.get("summary", ""), str(fields.get("description", ""))]
        for val in values:
            match = re.search(r"DIM\s+Solution\s+ID\s*[:#-]?\s*([A-Za-z0-9_-]+)", val, re.I)
            if match:
                return match.group(1)
        return ""

    def download_attachment(self, attachment, destination):
        response = self._request("GET", attachment.url, stream=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as stream:
            for chunk in response.iter_content(65536):
                if chunk:
                    stream.write(chunk)
        return destination

    def add_comment(self, key, text, dry_run=True):
        if dry_run:
            log.info("DRY RUN Jira comment: issue=%s chars=%d", key, len(text))
            return
        self._request("POST", f"{self.base_url}/rest/api/3/issue/{key}/comment", json={"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}})

    def comment_exists(self, key, marker):
        start = 0
        while True:
            data = self._request("GET", f"{self.base_url}/rest/api/3/issue/{key}/comment", params={"startAt": start, "maxResults": 100}).json()
            for comment in data.get("comments", []):
                if marker in str(comment.get("body", "")):
                    return True
            start += len(data.get("comments", []))
            if not data.get("comments") or start >= data.get("total", 0):
                return False

    def transition(self, key, target_status, dry_run=True):
        if dry_run:
            log.info("DRY RUN Jira transition: issue=%s target=%s", key, target_status)
            return False
        data = self._request("GET", f"{self.base_url}/rest/api/3/issue/{key}/transitions").json()
        transition = next((t for t in data.get("transitions", []) if t.get("to", {}).get("name") == target_status), None)
        if not transition:
            log.warning("Configured Jira transition unavailable: issue=%s target=%s", key, target_status)
            return False
        self._request("POST", f"{self.base_url}/rest/api/3/issue/{key}/transitions", json={"transition": {"id": transition["id"]}})
        return True
