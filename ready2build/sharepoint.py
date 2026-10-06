import logging
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)


class SharePointUploader:
    """Upload sanitized review copies through Microsoft Graph client credentials."""

    def __init__(self, tenant_id, client_id, client_secret, site_id, drive_id, folder="Ready2Build/IDD", session=None):
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.site_id, self.drive_id, self.folder = site_id, drive_id, folder.strip("/")
        self.session = session or requests.Session()
        self._token = None

    def _access_token(self):
        if not self._token:
            response = self.session.post(f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                data={"client_id": self.client_id, "client_secret": self.client_secret,
                      "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}, timeout=30)
            response.raise_for_status()
            self._token = response.json()["access_token"]
        return self._token

    def upload(self, path, correlation_id, dry_run=False):
        target = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/root:/{self.folder}/{quote(path.name, safe='')}"
        if dry_run:
            log.info("DRY RUN SharePoint upload: file=%s target=%s correlation=%s", path.name, target, correlation_id)
            return target
        if not all((self.tenant_id, self.client_id, self.client_secret, self.site_id, self.drive_id)):
            raise ValueError("SharePoint upload requires tenant, client, secret, site, and drive configuration")
        with path.open("rb") as stream:
            response = self.session.put(target + ":/content", headers={"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/octet-stream"}, data=stream, timeout=120)
        response.raise_for_status()
        item = response.json()
        return item.get("webUrl", target)
