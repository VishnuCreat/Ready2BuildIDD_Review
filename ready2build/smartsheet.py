import logging
import requests

log = logging.getLogger(__name__)


class SmartsheetClient:
    def __init__(self, token, sheet_id, columns, session=None):
        self.token, self.sheet_id, self.columns = token, sheet_id, columns or {}
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.base = "https://api.smartsheet.com/2.0"

    def find_row(self, jira_key, dim_id):
        data = self.session.get(f"{self.base}/sheets/{self.sheet_id}", params={"include": "columns"}, timeout=60)
        data.raise_for_status()
        col_map = {str(c["id"]): c["index"] for c in data.json().get("columns", [])}
        names = {v: k for k, v in self.columns.items()}
        key_idx, dim_idx = col_map.get(str(self.columns.get("jira_key"))), col_map.get(str(self.columns.get("dim_solution_id")))
        matches = []
        for row in data.json().get("rows", []):
            cells = {c["columnId"]: c.get("value") for c in row.get("cells", [])}
            if key_idx is not None and dim_idx is not None and str(cells.get(int(self.columns["jira_key"]), "")) == jira_key and str(cells.get(int(self.columns["dim_solution_id"]), "")) == dim_id:
                matches.append(row)
        if len(matches) > 1:
            log.error("Multiple Smartsheet rows match Jira key and DIM Solution ID: %s", jira_key)
        return matches[0] if matches else None

    def upsert(self, jira_key, dim_id, values, correlation_id, dry_run=True):
        row = self.find_row(jira_key, dim_id) if not dry_run else None
        cells = [{"columnId": int(self.columns[k]), "value": v} for k, v in {"jira_key": jira_key, "dim_solution_id": dim_id, **values}.items() if k in self.columns]
        if dry_run:
            log.info("DRY RUN Smartsheet row upsert: issue=%s dim=%s fields=%d correlation=%s", jira_key, dim_id, len(cells), correlation_id)
            return
        if row:
            self.session.put(f"{self.base}/sheets/{self.sheet_id}/rows", json=[{"id": row["id"], "cells": cells}], timeout=60).raise_for_status()
        else:
            self.session.post(f"{self.base}/sheets/{self.sheet_id}/rows", json=[{"toBottom": True, "cells": cells}], timeout=60).raise_for_status()
