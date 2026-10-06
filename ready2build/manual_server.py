"""Dependency-light local manual upload POC server."""
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import uuid

from .config import Config
from .codex_cli import CodexCLIReviewer
from .documents import available_extensions, extract_text
from .implementation import merge_implementation_names
from .llm import LLMReviewer
from .sanitizer import sanitize
from .scoring import score_review

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _e(value):
    return html.escape(str(value), quote=True)


def _page(body=""):
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#071626"><title>Ready2Build | IDD Review</title><style>
:root{color-scheme:light;--navy:#071626;--ink:#14263b;--muted:#64748b;--line:#e1e8ef;--blue:#1769aa;--teal:#20b6a2;--paper:#f5f8fb;--white:#fff;--shadow:0 18px 55px rgba(17,43,68,.09)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 72% -12%,#e5f5f6 0,transparent 38%),var(--paper);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink)}
.shell{max-width:1160px;margin:0 auto;padding:0 28px}.topbar{height:76px;background:rgba(255,255,255,.88);border-bottom:1px solid rgba(220,229,237,.9);display:flex;align-items:center;position:relative}.nav{display:flex;align-items:center;justify-content:space-between;width:100%}.brand{display:flex;align-items:center;gap:12px;color:var(--ink);text-decoration:none;font-weight:750;letter-spacing:-.03em;font-size:18px}.mark{width:38px;height:38px;border-radius:12px;background:linear-gradient(140deg,#0d3b60,#1786a0);display:grid;place-items:center;color:#fff;font-weight:800;box-shadow:0 5px 16px #0e759533}.brand small{display:block;color:var(--muted);font-size:10px;font-weight:650;letter-spacing:.13em;text-transform:uppercase;line-height:1.2}.navright{display:flex;gap:12px;align-items:center}.pill{display:inline-flex;align-items:center;gap:7px;padding:7px 11px;border:1px solid var(--line);border-radius:999px;background:#fff;color:#476074;font-size:12px;font-weight:650}.dot{width:7px;height:7px;border-radius:50%;background:var(--teal);box-shadow:0 0 0 3px #20b6a21a}.main{padding:43px 0 72px}.eyebrow{color:#178078;font-size:11px;text-transform:uppercase;letter-spacing:.17em;font-weight:800;display:flex;align-items:center;gap:9px}.eyebrow:before{content:"";height:1px;width:22px;background:#20a995}.hero{max-width:730px;margin-bottom:27px}.hero h1{font-size:clamp(34px,5vw,53px);line-height:1.07;letter-spacing:-.055em;margin:15px 0;color:#10243a;font-weight:760}.hero h1 span{color:#13827c}.hero p{font-size:16px;color:#62768a;max-width:640px;margin:0}.grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(270px,.78fr);gap:20px;align-items:start}.card{background:#fff;border:1px solid #e4ebf1;border-radius:18px;padding:25px;box-shadow:var(--shadow)}.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:20px}.card h2{font-size:18px;letter-spacing:-.025em;margin:0 0 5px}.sub{color:var(--muted);font-size:13px;margin:0}.step{font-size:11px;color:#62768a;background:#f3f7fa;border:1px solid #e5ecf2;border-radius:999px;padding:6px 10px;font-weight:700;white-space:nowrap}.dropzone{border:1.5px dashed #b8cbd8;border-radius:15px;background:linear-gradient(145deg,#f8fcfd,#f4f9fb);min-height:215px;display:flex;align-items:center;justify-content:center;text-align:center;padding:25px;transition:.2s}.dropzone.active{border-color:#169a90;background:#effbf8;box-shadow:inset 0 0 0 3px #20b6a214}.upload-icon{width:49px;height:49px;margin:0 auto 11px;border-radius:15px;background:#e6f4f4;color:#16837c;display:grid;place-items:center;font-size:22px}.dropzone strong{display:block;color:#1a3148;font-size:15px}.dropzone p{font-size:12px;color:var(--muted);margin:5px 0 11px}.browse{color:#137f79;text-decoration:underline;text-underline-offset:3px;font-weight:700;cursor:pointer}.filename{min-height:20px;color:#157d77;font-size:12px;font-weight:650}.file-input{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}.actions{display:flex;align-items:center;gap:14px;margin-top:17px}.button{appearance:none;border:0;border-radius:10px;padding:13px 18px;color:#fff;background:linear-gradient(110deg,#145a91,#127f85);font:inherit;font-weight:730;cursor:pointer;box-shadow:0 8px 20px #126c8330;transition:transform .15s,box-shadow .15s}.button:hover{transform:translateY(-1px);box-shadow:0 11px 25px #126c8340}.button:disabled{opacity:.48;cursor:not-allowed;transform:none}.secure{font-size:11px;color:#718398}.side-card{padding:22px}.side-title{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:#546a7e;font-weight:800;margin:0 0 15px}.flow{display:grid;gap:14px}.flowitem{display:grid;grid-template-columns:30px 1fr;gap:11px;align-items:start}.flowicon{width:28px;height:28px;border-radius:9px;background:#eef6f7;color:#167f7c;display:grid;place-items:center;font-size:12px;font-weight:800}.flowitem b{font-size:13px;display:block}.flowitem span{font-size:11px;color:var(--muted);display:block;margin-top:2px}.safe-box{margin-top:19px;padding:13px;border-radius:12px;background:#f0f8f6;border:1px solid #dcefeb;color:#42665f;font-size:11px}.safe-box b{display:block;color:#21665e;margin-bottom:3px}.format-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.format{font-size:10px;font-weight:750;color:#546b80;background:#f2f5f8;border:1px solid #e7edf2;padding:4px 7px;border-radius:6px}.footer{margin-top:22px;color:#8a9aaa;font-size:11px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
.notice{padding:14px 16px;border-radius:12px;margin:0 0 18px;font-size:13px}.warn{background:#fff8e5;border:1px solid #f2dfa6;color:#795b16}.ok{background:#edfaf4;border:1px solid #ccebdd;color:#246747}.result-head{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.back{color:#167c80;text-decoration:none;font-size:13px;font-weight:700}.result-title{margin:19px 0 22px}.result-title h1{font-size:30px;letter-spacing:-.04em;margin:5px 0 5px;overflow-wrap:anywhere}.result-title p{margin:0;color:var(--muted);font-size:13px}.metric-grid{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:14px;margin:18px 0}.metric{background:#fff;border:1px solid var(--line);border-radius:15px;padding:19px;box-shadow:0 8px 24px #1a36510a}.metric-label{font-size:11px;font-weight:750;color:#75869a;text-transform:uppercase;letter-spacing:.09em}.metric-value{font-size:27px;font-weight:770;letter-spacing:-.05em;margin-top:4px;color:#16334c}.metric-note{font-size:11px;color:var(--muted);margin-top:3px}.scorebar{height:5px;background:#edf2f5;border-radius:99px;margin-top:10px;overflow:hidden}.scorebar i{display:block;height:100%;background:linear-gradient(90deg,#20b6a2,#297bb1);border-radius:99px}.complexity{display:inline-flex;padding:6px 10px;border-radius:999px;font-size:12px;font-weight:750;background:#eef4fa;color:#39617e}.complexity.low{background:#e9f8f1;color:#26704d}.complexity.medium{background:#fff5df;color:#936718}.complexity.high{background:#fff0ed;color:#b24a39}.complexity.undetermined{background:#eef1f5;color:#68788a}.section{margin-top:20px}.section h2{font-size:15px;margin:0 0 12px;letter-spacing:-.015em}.rationale{border-left:3px solid #1c988f;background:#f0f8f7;padding:13px 15px;border-radius:0 10px 10px 0;color:#45656a;font-size:13px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;background:white}th,td{text-align:left;border-bottom:1px solid #edf1f4;padding:12px 14px;vertical-align:top;font-size:12px}th{background:#f7f9fb;color:#63768a;text-transform:uppercase;letter-spacing:.07em;font-size:10px}tr:last-child td{border-bottom:0}.score-cell{white-space:nowrap;font-weight:750;color:#176b77}.factor-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:9px}.factor{border:1px solid var(--line);border-radius:11px;padding:12px}.factor span{display:block;font-size:10px;color:#728397;text-transform:uppercase;letter-spacing:.06em;font-weight:700}.factor b{font-size:18px;display:block;margin-top:2px}.result-columns{display:grid;grid-template-columns:1fr 1fr;gap:15px}.list-card{border:1px solid var(--line);border-radius:13px;padding:16px;background:white}.list-card h3{margin:0 0 9px;font-size:13px}.list-card ul{margin:0;padding-left:18px;color:#536b7f;font-size:12px}.list-card li+li{margin-top:6px}.empty{color:#91a0ae;font-size:12px}.meta{font-size:11px;color:#8392a1;overflow-wrap:anywhere}details{margin-top:19px;border:1px solid var(--line);background:white;border-radius:12px;padding:13px 15px}summary{cursor:pointer;color:#536c80;font-size:12px;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:14px;border-radius:9px;max-height:420px;overflow:auto;font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}.error-card{max-width:700px;margin:55px auto}
@media(max-width:820px){.grid{grid-template-columns:1fr}.side-card{order:2}.main{padding-top:30px}.metric-grid{grid-template-columns:1fr 1fr}.metric:first-child{grid-column:span 2}}
@media(max-width:560px){.shell{padding:0 16px}.topbar{height:66px}.navright .pill:first-child{display:none}.main{padding-top:24px}.hero h1{font-size:37px}.card{padding:19px;border-radius:15px}.metric-grid{gap:8px}.metric{padding:14px}.metric-value{font-size:23px}.result-columns{grid-template-columns:1fr}.footer span:last-child{display:none}}
</style></head><body><header class="topbar"><div class="shell nav"><a class="brand" href="/"><span class="mark">R2</span><span>Ready2Build<small>Integration design review</small></span></a><div class="navright"><span class="pill"><i class="dot"></i> Local workspace</span><span class="pill">IDD REVIEW</span></div></div></header><main class="shell main">""" + body + "</main></body></html>"


def _form(config):
    exts = sorted(x.lstrip(".") for x in available_extensions())
    format_tags = "".join(f'<span class="format">{_e(x.upper())}</span>' for x in exts)
    return _page(f'''<section class="hero"><div class="eyebrow">Integration readiness workspace</div><h1>Make every IDD <span>build-ready.</span></h1><p>Review integration design documents for readiness, implementation complexity, and the questions your team needs answered before build.</p></section>
<div class="grid"><section class="card"><div class="card-head"><div><h2>Start an IDD review</h2><p class="sub">Add a document to generate an evidence-based assessment.</p></div><span class="step">01 &nbsp; DOCUMENT</span></div>
<form id="upload-form" method="post" enctype="multipart/form-data"><label class="dropzone" id="dropzone" for="idd"><input class="file-input" id="idd" name="idd" type="file" accept="{_e(",".join("."+x for x in exts))}" required>
<span><span class="upload-icon">↑</span><strong>Drop your IDD here</strong><p>or <span class="browse">browse files</span> on your device</p><span class="filename" id="filename">Choose a file to see its name here</span></span></label>
<div class="actions"><button class="button" id="submit" type="submit" disabled>Review IDD <span aria-hidden="true">→</span></button><span class="secure">Secure local processing · Original stays on this device</span></div></form></section>
<aside class="card side-card"><h2 class="side-title">What happens next</h2><div class="flow"><div class="flowitem"><span class="flowicon">1</span><div><b>Extract and sanitize</b><span>Redact likely sensitive values before review.</span></div></div><div class="flowitem"><span class="flowicon">2</span><div><b>Assess readiness</b><span>Score completeness across six IDD criteria.</span></div></div><div class="flowitem"><span class="flowicon">3</span><div><b>Classify build complexity</b><span>Use documented APIs, shapes, scripts and logic.</span></div></div></div>
<div class="safe-box"><b>Privacy-first review</b>Only the sanitized document text is sent to the configured reviewer. The original remains local.</div><p class="side-title" style="margin:17px 0 0">Readable formats</p><div class="format-list">{format_tags}</div></aside></div>
<div class="footer"><span>READY2BUILD · IDD REVIEW</span><span>Reviewer: {_e(config.llm_provider if config.llm_enabled else "Not configured")} &nbsp;·&nbsp; Jira and Smartsheet are not connected in this manual POC</span></div>
<script>(()=>{{const input=document.getElementById('idd'),zone=document.getElementById('dropzone'),name=document.getElementById('filename'),button=document.getElementById('submit');const show=()=>{{name.textContent=input.files&&input.files[0]?input.files[0].name:'Choose a file to see its name here';button.disabled=!(input.files&&input.files.length)}};input.addEventListener('change',show);for(const e of ['dragenter','dragover'])zone.addEventListener(e,x=>{{x.preventDefault();zone.classList.add('active')}});for(const e of ['dragleave','drop'])zone.addEventListener(e,x=>{{x.preventDefault();zone.classList.remove('active')}});zone.addEventListener('drop',e=>{{if(e.dataTransfer.files.length){{input.files=e.dataTransfer.files;show()}}}});document.getElementById('upload-form').addEventListener('submit',()=>{{button.disabled=true;button.textContent='Reviewing sanitized IDD…'}})}})();</script>''')


def _review_upload(filename, content, config):
    suffix = Path(filename).suffix.lower()
    if suffix not in available_extensions():
        raise ValueError("This file type is not readable in the current environment. Supported: " + ", ".join(sorted(available_extensions())))
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).name)[:120]
    digest = hashlib.sha256(content).hexdigest()
    correlation = str(uuid.uuid5(uuid.NAMESPACE_URL, digest))
    original = config.download_dir.parent / "manual" / "original" / safe_name
    sanitized = config.sanitized_dir / "manual" / (Path(safe_name).stem + ".txt")
    original.parent.mkdir(parents=True, exist_ok=True)
    sanitized.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(content)
    text = extract_text(original)
    clean = sanitize(text, config.sanitizer_patterns)
    if not clean.strip():
        raise ValueError("No readable text found in the file")
    sanitized.write_text(clean, encoding="utf-8")
    if config.llm_enabled:
        if config.llm_provider == "codex_cli":
            payload = CodexCLIReviewer(config.codex_cli_path, config.codex_model, workspace_dir=config.ledger_path.parent).review(clean)
        elif config.llm_provider == "api":
            if not config.llm_api_key or not config.llm_model:
                raise ValueError("LLM_PROVIDER=api requires LLM_API_KEY and LLM_MODEL")
            payload = LLMReviewer(config.llm_base_url, config.llm_api_key, config.llm_model).review(clean)
        else:
            raise ValueError("LLM_PROVIDER must be 'api' or 'codex_cli'")
        payload = merge_implementation_names(payload, clean)
        review = score_review(payload)
    else:
        review = None
    result = {"filename": filename, "correlation_id": correlation, "reviewed_at": datetime.now(timezone.utc).isoformat(), "review": review.to_dict() if review else None, "status": "reviewed" if review else "sanitized_llm_not_configured", "reviewer": config.llm_provider if review else "none", "model": (config.codex_model or "Codex CLI default") if config.llm_provider == "codex_cli" and review else config.llm_model if review else "", "sanitized_file": str(sanitized)}
    result_dir = config.ledger_path.parent / "manual-results"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{correlation}.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return review, sanitized, result_path, correlation, clean


def _result_page(filename, review, sanitized, result_path, correlation, clean, config):
    if review is None:
        return _page(f'''<div class="result-head"><a class="back" href="/">← &nbsp; New review</a><span class="pill">DOCUMENT SANITIZED</span></div><section class="card error-card"><div class="eyebrow">Assessment not configured</div><div class="result-title"><h1>{_e(filename)}</h1><p>Your document was extracted and sanitized. No readiness or complexity assessment was generated.</p></div>
<div class="notice warn">Enable the local Codex reviewer in <code>.env</code> with <code>LLM_ENABLED=true</code> and <code>LLM_PROVIDER=codex_cli</code>, then restart the app and upload again.</div><p class="meta">Correlation ID: {_e(correlation)}<br>Sanitized copy: {_e(sanitized)}<br>Result: {_e(result_path)}</p></section>
<details><summary>Sanitized text (not sent to a reviewer)</summary><pre>{_e(clean)}</pre></details>''')
    rows = "".join(f"<tr><td>{_e(s.name.replace('_',' ').title())}</td><td>{s.score}/5</td><td>{_e(s.reason)}</td></tr>" for s in review.scores)
    sections = ""
    for title, vals in [("Key findings", review.findings), ("Missing information", review.missing_information),
                        ("Clarification questions", review.clarification_questions), ("Risks", review.risks), ("Assumptions", review.assumptions)]:
        content = "<ul>" + "".join(f"<li>{_e(v)}</li>" for v in vals) + "</ul>" if vals else '<span class="empty">None reported</span>'
        sections += f'<article class="list-card"><h3>{_e(title)}</h3>{content}</article>'
    status_notice = ('<div class="notice warn">Assessment is provisional. Some implementation or requirement details need clarification.</div>' if review.provisional else '<div class="notice ok">Review complete · assessment is based on evidence in the sanitized IDD.</div>')
    factors = review.implementation_factors
    assessment_html = ""
    for assessment in review.template_assessments:
        task_rows = "".join(f"<tr><td>{_e(task.get('task', ''))}</td><td>{_e(task.get('hours', 0))}</td><td>{_e(task.get('evidence', ''))}</td></tr>" for task in assessment.get("tasks", []) if isinstance(task, dict))
        questions = assessment.get("clarification_questions", []) or assessment.get("missing_information", [])
        question_html = "<ul>" + "".join(f"<li>{_e(q)}</li>" for q in questions) + "</ul>" if questions else "None reported"
        assessment_html += f'''<section class="card section"><h2>{_e(assessment['template_type'])} · {_e(assessment['complexity'])}{' · Provisional' if assessment.get('total_hours') is None else ''}</h2><p><b>Estimated total:</b> {_e(assessment.get('total_hours') if assessment.get('total_hours') is not None else 'Undetermined')} Boomi consultant hours. {_e(assessment['classification_reason'])}</p><p><b>Evidence:</b> {_e(assessment.get('evidence', 'Not stated'))}</p><div class="table-wrap"><table><thead><tr><th>Task</th><th>Hours</th><th>IDD evidence</th></tr></thead><tbody>{task_rows}</tbody></table></div><p><b>Assumptions / exclusions:</b> {_e('; '.join(assessment.get('assumptions', [])) or 'None stated')}</p><p><b>Missing information / questions:</b> {question_html}</p><p><b>Confidence:</b> {_e(assessment.get('confidence', 'Not stated'))}</p></section>'''
    integration_name = factors.get("integration_name")
    template_names = factors.get("template_names_mentioned") or []
    display_names = template_names or ([integration_name] if integration_name else [])
    template_names_html = "".join(f'<span class="format">{_e(name)}</span>' for name in display_names) or '<span class="empty">No template or integration name stated</span>'
    factor_cards = "".join(f'<div class="factor"><span>{_e(k.replace("_"," "))}</span><b>{_e(v if v is not None else "Not stated")}</b></div>' for k, v in factors.items() if k not in ("evidence", "simple_mapping_only", "template_names_mentioned", "integration_name", "templates"))
    complexity_class = review.complexity.lower() if review.complexity.lower() in ("low", "medium", "high") else "undetermined"
    return _page(f'''<div class="result-head"><a class="back" href="/">← &nbsp; New review</a><span class="pill"><i class="dot"></i> REVIEW COMPLETE</span></div>
<div class="result-title"><div class="eyebrow">IDD assessment</div><h1>{_e(filename)}</h1><p>Evidence-based readiness and implementation review &nbsp;·&nbsp; {_e(review.status)}</p></div>{status_notice}
<div class="metric-grid"><div class="metric"><div class="metric-label">Overall Ready-to-Build Score</div><div class="metric-value">{_e(review.readiness_score)}<span style="font-size:14px;color:#8191a0"> / 100</span></div><div class="scorebar"><i style="width:{max(0,min(100,review.readiness_score))}%"></i></div><div class="metric-note">IDD completeness across six criteria</div></div>
<div class="metric"><div class="metric-label">Implementation complexity</div><div style="margin-top:9px"><span class="complexity {complexity_class}">{_e(review.complexity)}{" · Provisional" if review.provisional else ""}</span></div><div class="metric-note">Based on documented Boomi effort in the IDD</div></div>
<div class="metric"><div class="metric-label">Review model</div><div class="metric-value" style="font-size:17px;margin-top:10px">{_e(config.llm_provider)}</div><div class="metric-note">{_e(config.codex_model or "Codex CLI default" if config.llm_provider == "codex_cli" else config.llm_model)}</div></div></div>
<section class="card section"><h2>Implementation complexity rationale</h2><div class="rationale">{_e(review.complexity_reason)}</div><div class="factor-grid" style="margin-top:14px"><div class="factor"><span>Template / integration name</span><b>{template_names_html}</b><span style="display:block;margin-top:7px">Template count: {_e(factors.get('templates') if factors.get('templates') is not None else 'Not stated')}</span></div>{factor_cards}</div><p class="sub" style="margin:12px 0 0">Integration Name field: <b>{_e(integration_name or 'Not stated in IDD')}</b>. {_e(factors.get('evidence', 'No implementation evidence was returned.'))}</p></section>
{assessment_html}
<section class="card section"><h2>Readiness criteria</h2><p class="sub" style="margin-bottom:14px">These scores reflect how clearly and completely the IDD documents each area.</p><div class="table-wrap"><table><thead><tr><th>Criterion</th><th>Score</th><th>Evidence and rationale</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section class="section result-columns">{sections}</section><section class="card section"><h2>Reviewer notes</h2><p class="sub">{_e(review.reviewer_notes or "No additional reviewer notes.")}</p></section>
<p class="meta" style="margin-top:17px">Correlation ID: {_e(correlation)}<br>Sanitized copy: {_e(sanitized)}<br>Result record: {_e(result_path)}</p>
<details><summary>Sanitized text sent to the reviewer</summary><pre>{_e(clean)}</pre></details>''')


class Handler(BaseHTTPRequestHandler):
    config = None

    def log_message(self, fmt, *args):
        logging.getLogger("ready2build.web").info("local web request: %s", fmt % args)

    def _send(self, status, body):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/results/"):
            correlation = self.path.rsplit("/", 1)[-1]
            result_path = self.config.ledger_path.parent / "manual-results" / f"{correlation}.json"
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                sanitized = Path(result["sanitized_file"])
                clean = sanitized.read_text(encoding="utf-8")
                review = None
                if result.get("review"):
                    from .models import CriterionScore, Review
                    data = result["review"]
                    data["scores"] = [CriterionScore(**score) for score in data.get("scores", [])]
                    review = Review(**data)
                body = _result_page(result.get("filename", "IDD file"), review, sanitized, result_path, correlation, clean, self.config)
                self._send(200, body)
            except Exception:
                self._send(404, _page("<p>Review result not found.</p>"))
            return
        self._send(200, _form(self.config))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            return self._send(413, _page("<h2>File too large</h2><p>Maximum upload size is 20 MB.</p>"))
        raw = self.rfile.read(length)
        header = f"Content-Type: {self.headers.get('Content-Type', '')}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        try:
            message = BytesParser(policy=policy.default).parsebytes(header + raw)
            part = next((p for p in message.iter_parts() if p.get_param("name", header="content-disposition") == "idd" and p.get_filename()), None)
            if part is None:
                raise ValueError("Choose a file before submitting")
            review, sanitized, result, correlation, clean = _review_upload(part.get_filename(), part.get_payload(decode=True) or b"", self.config)
            self._send(200, _result_page(part.get_filename(), review, sanitized, result, correlation, clean, self.config))
        except Exception as exc:
            logging.getLogger("ready2build.web").warning("Manual upload failed: error=%s", type(exc).__name__)
            self._send(400, _page(f"<section class='card'><p class='warn'>Upload/review failed: {_e(str(exc))}</p><p><a href='/'>Return to upload</a></p></section>"))


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    config = Config.from_env()
    Handler.config = config
    parser = argparse.ArgumentParser(description="Ready2Build manual upload POC")
    parser.add_argument("--port", type=int, default=int(os.getenv("READY2BUILD_PORT", "8501")))
    port = parser.parse_args().port
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Ready2Build manual POC: http://localhost:{port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
