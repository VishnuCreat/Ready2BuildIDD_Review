import argparse
import logging
import os
import time

from .config import Config
from .jira import JiraClient
from .ledger import Ledger
from .processor import Processor
from .smartsheet import SmartsheetClient
from .llm import LLMReviewer
from .sharepoint import SharePointUploader


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def main(argv=None):
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Ready2Build IID review queue")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Process the current queue once")
    mode.add_argument("--poll", action="store_true", help="Poll continuously")
    parser.add_argument("--reprocess", metavar="KEY", help="Force processing of one issue")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = Config.from_env()
    config.validate_jira_read()
    jira = JiraClient(config.jira_base_url, config.jira_email, config.jira_api_token, dim_field=config.jira_dim_field)
    sheet = None
    if config.smartsheet_access_token and config.smartsheet_sheet_id:
        sheet = SmartsheetClient(config.smartsheet_access_token, config.smartsheet_sheet_id, config.smartsheet_columns)
    llm = LLMReviewer(config.llm_base_url, config.llm_api_key, config.llm_model) if config.llm_enabled else None
    uploader = None
    if config.sharepoint_enabled and all((config.sharepoint_tenant_id, config.sharepoint_client_id, config.sharepoint_client_secret, config.sharepoint_site_id, config.sharepoint_drive_id)):
        uploader = SharePointUploader(config.sharepoint_tenant_id, config.sharepoint_client_id, config.sharepoint_client_secret,
                                      config.sharepoint_site_id, config.sharepoint_drive_id, config.sharepoint_folder)
    processor = Processor(config, jira, Ledger(config.ledger_path), sheet, llm, uploader)
    while True:
        jql = config.jira_jql
        if config.jira_project and "project" not in jql.lower():
            jql = f"project = {config.jira_project} AND ({jql})"
        for issue in jira.search_issues(jql):
            if args.reprocess and args.reprocess != issue.key:
                continue
            processor.process(issue, reprocess=bool(args.reprocess))
        flagged = processor.follow_up_items()
        if flagged:
            logging.getLogger(__name__).warning("Follow-up flag: clarification outstanding >=3 business days for %s", ", ".join(flagged))
        if not args.poll:
            break
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
