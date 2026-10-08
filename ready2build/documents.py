import csv
import importlib.util
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

log = logging.getLogger(__name__)
SUPPORTED = {".pdf", ".docx", ".xlsx", ".csv", ".txt"}


def available_extensions():
    """Formats readable with the currently installed document libraries."""
    result = {".csv", ".txt"}
    if importlib.util.find_spec("openpyxl"):
        result.add(".xlsx")
    if importlib.util.find_spec("pypdf"):
        result.add(".pdf")
    # DOCX is a ZIP/XML format and has a standard-library fallback below.
    result.add(".docx")
    return result


def missing_document_readers():
    """Return install hints for formats whose optional reader is unavailable."""
    return {
        suffix: package for suffix, module, package in (
            (".pdf", "pypdf", "pypdf"),
            (".xlsx", "openpyxl", "openpyxl"),
        ) if importlib.util.find_spec(module) is None
    }


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"Unsupported attachment format: {suffix or 'unknown'}")
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="", errors="replace") as f:
            return "\n".join(", ".join(row) for row in csv.reader(f))
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Install the documents extra to read PDF files") from exc
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError:
            # Extract paragraph text, including paragraphs inside table cells,
            # without requiring a third-party package.
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read("word/document.xml"))
            paragraph_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
            text_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            paragraphs = ["".join(node.text or "" for node in paragraph.iter(text_tag))
                          for paragraph in root.iter(paragraph_tag)]
            return "\n".join(text for text in paragraphs if text)
        doc = Document(path)
        return "\n".join([p.text for p in doc.paragraphs] + [" | ".join(c.text for c in row.cells) for table in doc.tables for row in table.rows])
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("Install the documents extra to read XLSX files") from exc
    workbook = load_workbook(path, read_only=True, data_only=True)
    return "\n".join(" | ".join(str(c) if c is not None else "" for c in row) for sheet in workbook for row in sheet.iter_rows(values_only=True))
