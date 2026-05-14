"""
Invoice Processing Portal - Backend server for the web UI.

Serves the portal (portal/index.html), handles document upload, runs the
Azure AI Foundry workflow in the background, streams progress via SSE,
and processes approval/rejection.

Endpoints:
  GET  /              - Portal UI (index.html)
  POST /api/upload    - Upload invoice, PO, GRN; start workflow; returns session_id
  GET  /api/progress/<session_id> - SSE stream of workflow progress
  POST /api/approve/<session_id>?decision=APPROVE|REJECT - Submit approval decision

Run: python invoice_portal.py
Then open http://localhost:5000
"""

import os
import sys
import json
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
import re


def _utc_ts():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# -----------------------------------------------------------------------------
# Azure response stream event type constants
# -----------------------------------------------------------------------------
# Newer versions of azure-ai-projects do not expose ResponseStreamEventType from
# azure.ai.projects.models, so use the raw event.type string values instead.
RESPONSE_OUTPUT_TEXT_DELTA = "response.output_text.delta"
RESPONSE_OUTPUT_TEXT_DONE = "response.output_text.done"
RESPONSE_OUTPUT_ITEM_ADDED = "response.output_item.added"
RESPONSE_OUTPUT_ITEM_DONE = "response.output_item.done"
ERROR = "error"


def _extract_step_summary(action_id, text):
    """Extract meaningful summary and details from step output."""
    text = text.strip()
    details = {}
    summary = ""

    if action_id == "invoke-extractor":
        inv_match = re.search(r"Invoice\s*(?:#|Number|No\.?)?\s*[:\s]*([A-Z0-9\-]+)", text, re.I)
        amt_match = re.search(r"(?:Total|Amount|Grand Total)[:\s]*\$?([\d,]+\.?\d*)", text, re.I)
        vendor_match = re.search(r"(?:Vendor|Supplier|From)[:\s]*([^\n\r,]+)", text, re.I)

        if inv_match:
            details["invoice_number"] = inv_match.group(1).strip()
        if amt_match:
            details["amount"] = amt_match.group(1).strip()
        if vendor_match:
            details["vendor"] = vendor_match.group(1).strip()[:50]

        if details:
            parts = []
            if details.get("invoice_number"):
                parts.append(f"Invoice #{details['invoice_number']}")
            if details.get("amount"):
                parts.append(f"${details['amount']}")
            if details.get("vendor"):
                parts.append(f"from {details['vendor']}")
            summary = "Extracted: " + ", ".join(parts) if parts else "Document data extracted"
        else:
            summary = "Document data extracted successfully"

    elif action_id == "invoke-matcher":
        qty_match = re.search(r"(?:quantity|qty)[:\s]*([\d,]+)", text, re.I)
        price_match = re.search(r"(?:unit price|price)[:\s]*\$?([\d,]+\.?\d*)", text, re.I)

        if "mismatch" in text.lower() or "discrepanc" in text.lower():
            details["result"] = "discrepancies found"
            summary = "Three-way matching: Discrepancies found"
        elif "match" in text.lower():
            details["result"] = "all matched"
            summary = "Three-way matching: Invoice, PO, and GRN match"
        else:
            summary = "Three-way matching completed"

        if qty_match:
            details["quantity"] = qty_match.group(1)
        if price_match:
            details["unit_price"] = price_match.group(1)

    elif action_id == "invoke-sql-validator":
        if "valid" in text.lower():
            if "invalid" in text.lower() or "not valid" in text.lower():
                details["validation"] = "issues found"
                summary = "Database validation: Some issues detected"
            else:
                details["validation"] = "passed"
                summary = "Database validation: All records verified"

        po_match = re.search(r"PO[:\s#]*([A-Z0-9\-]+)", text, re.I)
        if po_match:
            details["po_number"] = po_match.group(1)
            summary = f"Database validation: PO {details['po_number']} verified"

        if not summary:
            summary = "Database validation completed"

    elif action_id == "invoke-risk-scorer":
        score_match = re.search(r"(?:risk\s*score|score)[:\s]*([\d.]+)", text, re.I)
        level_match = re.search(r"(low|medium|high|critical)\s*risk", text, re.I)

        if score_match:
            details["risk_score"] = score_match.group(1)
        if level_match:
            details["risk_level"] = level_match.group(1).capitalize()

        if details.get("risk_score") or details.get("risk_level"):
            parts = []
            if details.get("risk_level"):
                parts.append(f"{details['risk_level']} Risk")
            if details.get("risk_score"):
                parts.append(f"Score: {details['risk_score']}")
            summary = "Risk Assessment: " + ", ".join(parts)
        else:
            summary = "Risk assessment completed"

    elif action_id == "invoke-payment-pack":
        summary = "Payment pack generated with invoice details"
        details["output"] = "Payment authorization document created"

    elif action_id == "invoke-approval-email":
        summary = "Approval notification sent to finance team"
        details["recipient"] = "Finance team"

    elif action_id == "invoke-rejection-email":
        summary = "Rejection notification sent to requester"
        details["recipient"] = "Requester"

    else:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if lines:
            summary = lines[0][:150]
        else:
            summary = f"Completed {action_id}"

    if text:
        details["raw_output"] = text[:2000] if len(text) > 2000 else text

    return {"summary": summary, "details": details}


# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

try:
    from flask import Flask, request, Response, send_from_directory
except ImportError as e:
    print("Flask import failed:", e)
    print("Install Flask: python -m pip install flask")
    sys.exit(1)

try:
    from azure.identity import DefaultAzureCredential
    from azure.ai.projects import AIProjectClient
except ImportError as e:
    print("Azure SDK import failed:", e)
    print("Install Azure SDK: python -m pip install azure-identity azure-ai-projects")
    sys.exit(1)


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
PORTAL_DIR = BASE_DIR / "portal"
UPLOADS_DIR = BASE_DIR / "uploads"
WORKFLOW_NAME = "Invoice-Processing-Workflow"
ENDPOINT = os.environ.get(
    "AZURE_AIPROJECT_ENDPOINT",
    "https://multiagentinvoiceprocessingsol.services.ai.azure.com/api/projects/MultiAgent-InvoiceProcessing",
)

UPLOADS_DIR.mkdir(exist_ok=True)

# Load .env if present
env_path = BASE_DIR / ".env"
if env_path.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        if os.environ.get("AZURE_AIPROJECT_ENDPOINT"):
            ENDPOINT = os.environ["AZURE_AIPROJECT_ENDPOINT"]
    except ImportError:
        pass


# -----------------------------------------------------------------------------
# Session store: session_id -> { conversation_id, events[], status, vector_store_id, file_ids, ... }
# -----------------------------------------------------------------------------
sessions = {}
sessions_lock = threading.Lock()


def emit(session_id, obj):
    with sessions_lock:
        if session_id in sessions:
            sessions[session_id]["events"].append(obj)


def cleanup_foundry_data(session_id):
    """Delete vector store and uploaded files from Foundry after workflow is done."""
    with sessions_lock:
        s = sessions.get(session_id)
        if not s:
            return
        vs_id = s.pop("vector_store_id", None)
        file_ids = s.pop("file_ids", []) or []

    if not vs_id:
        return

    try:
        cred = DefaultAzureCredential()
        client = AIProjectClient(endpoint=ENDPOINT, credential=cred)
        with client:
            oc = client.get_openai_client()
            try:
                oc.vector_stores.delete(vector_store_id=vs_id)
            except Exception:
                pass

            for fid in file_ids:
                try:
                    oc.files.delete(file_id=fid)
                except Exception:
                    pass
    except Exception:
        pass


def run_workflow_until_approval(session_id, doc_text, uploaded_paths=None):
    """Run workflow in background: upload to Foundry vector store, then Start + documents; stop when waiting for approval."""
    uploaded_paths = uploaded_paths or []

    try:
        cred = DefaultAzureCredential()
        client = AIProjectClient(endpoint=ENDPOINT, credential=cred)

        with client:
            oc = client.get_openai_client()
            vs_id = None
            file_ids = []

            if uploaded_paths:
                try:
                    emit(
                        session_id,
                        {
                            "type": "step",
                            "step": "foundry_upload",
                            "status": "active",
                            "message": "Uploading documents to Foundry and creating vector store...",
                            "timestamp": _utc_ts(),
                        },
                    )

                    vs = oc.vector_stores.create(name=f"InvoiceSession-{session_id[:20]}")
                    vs_id = vs.id

                    for path in uploaded_paths:
                        if path and Path(path).exists():
                            with open(path, "rb") as fh:
                                vf = oc.vector_stores.files.upload_and_poll(vector_store_id=vs_id, file=fh)
                            if getattr(vf, "id", None):
                                file_ids.append(vf.id)

                    with sessions_lock:
                        if session_id in sessions:
                            sessions[session_id]["vector_store_id"] = vs_id
                            sessions[session_id]["file_ids"] = file_ids

                    emit(
                        session_id,
                        {
                            "type": "step",
                            "step": "foundry_upload",
                            "status": "completed",
                            "message": "Documents vectorized in Foundry; feeding to document extractor.",
                            "data": {
                                "vector_store_id": vs_id[:20] + "..." if len(vs_id) > 20 else vs_id,
                                "files_uploaded": str(len(file_ids)),
                                "status": "Vectorization complete",
                            },
                            "timestamp": _utc_ts(),
                        },
                    )
                except Exception as vs_err:
                    emit(
                        session_id,
                        {
                            "type": "step",
                            "step": "foundry_upload",
                            "status": "error",
                            "message": str(vs_err),
                            "timestamp": _utc_ts(),
                        },
                    )
                    # Continue with doc_text only.

            conv = oc.conversations.create()
            with sessions_lock:
                if session_id not in sessions:
                    return
                sessions[session_id]["conversation_id"] = conv.id

            def stream_and_emit(stream, step_name):
                """Process stream events. Returns True if workflow is waiting for approval."""
                all_text = []
                last_text_index = 0
                last_completed_action_id = None
                saw_approval_question = False

                for event in stream:
                    if event.type == RESPONSE_OUTPUT_TEXT_DELTA:
                        d = getattr(event, "delta", "") or ""
                        all_text.append(d)

                    elif event.type == RESPONSE_OUTPUT_TEXT_DONE:
                        t = getattr(event, "text", "") or ""
                        if t:
                            all_text.append(t)

                    elif event.type == RESPONSE_OUTPUT_ITEM_ADDED:
                        if hasattr(event, "item") and getattr(event.item, "type", None) == "workflow_action":
                            aid = getattr(event.item, "action_id", None)
                            if aid:
                                last_text_index = len(all_text)
                                if aid == "approval-question":
                                    saw_approval_question = True
                                emit(
                                    session_id,
                                    {
                                        "type": "step",
                                        "step": aid,
                                        "status": "active",
                                        "message": f"Running {aid}..." if aid != "approval-question" else "Preparing approval...",
                                        "timestamp": _utc_ts(),
                                    },
                                )

                    elif event.type == RESPONSE_OUTPUT_ITEM_DONE:
                        if hasattr(event, "item") and getattr(event.item, "type", None) == "workflow_action":
                            aid = getattr(event.item, "action_id", None)
                            if aid:
                                last_completed_action_id = aid
                                step_text = "".join(all_text[last_text_index:]).strip()
                                print(f"[STEP] {aid} completed, text length: {len(step_text)}")
                                summary = _extract_step_summary(aid, step_text)
                                emit(
                                    session_id,
                                    {
                                        "type": "step",
                                        "step": aid,
                                        "status": "completed",
                                        "message": summary.get("summary", f"Completed {aid}"),
                                        "data": summary.get("details"),
                                        "timestamp": _utc_ts(),
                                    },
                                )
                                last_text_index = len(all_text)

                    elif event.type == ERROR:
                        err = getattr(event, "error", None) or str(event)
                        emit(
                            session_id,
                            {
                                "type": "step",
                                "step": "error",
                                "status": "error",
                                "message": str(err),
                                "timestamp": _utc_ts(),
                            },
                        )
                        with sessions_lock:
                            if session_id in sessions:
                                sessions[session_id]["status"] = "error"
                        return False

                full = "".join(all_text)
                waiting = (
                    saw_approval_question
                    or last_completed_action_id == "invoke-risk-scorer"
                    or ("APPROVE" in full.upper() and "REJECT" in full.upper())
                )
                print(
                    f"[STREAM] Finished, waiting={waiting}, "
                    f"saw_approval={saw_approval_question}, last_action={last_completed_action_id}"
                )
                return waiting

            stream1 = oc.responses.create(
                conversation=conv.id,
                extra_body={
    "agent_reference": {
        "name": WORKFLOW_NAME,
        "type": "agent_reference"
    }
},
                input="Start",
                stream=True,
                metadata={"x-ms-debug-mode-enabled": "1"},
            )
            stream_and_emit(stream1, "init")

            stream2 = oc.responses.create(
                conversation=conv.id,
                extra_body={
    "agent_reference": {
        "name": WORKFLOW_NAME,
        "type": "agent_reference"
    }
},
                input=doc_text,
                stream=True,
                metadata={"x-ms-debug-mode-enabled": "1"},
            )
            waiting = stream_and_emit(stream2, "documents")

            with sessions_lock:
                if session_id not in sessions:
                    return
                sessions[session_id]["stream_complete"] = True
                sessions[session_id]["status"] = "waiting" if waiting else "complete"
                print(f"[WORKFLOW] Stream complete, status={sessions[session_id]['status']}")

            if waiting:
                emit(
                    session_id,
                    {
                        "type": "step",
                        "step": "approval",
                        "status": "waiting",
                        "message": "Please APPROVE or REJECT this invoice.",
                        "show_approval_buttons": True,
                        "timestamp": _utc_ts(),
                    },
                )
            else:
                cleanup_foundry_data(session_id)

    except Exception as e:
        print("[WORKFLOW ERROR]", repr(e))
        import traceback
        traceback.print_exc()

        emit(
            session_id,
            {
                "type": "step",
                "step": "error",
                "status": "error",
                "message": str(e),
                "timestamp": _utc_ts(),
            },
        )
        with sessions_lock:
            if session_id in sessions:
                sessions[session_id]["status"] = "error"
        cleanup_foundry_data(session_id)


def run_workflow_approval(session_id, decision):
    """Send APPROVE/REJECT and run workflow to completion. Returns (response_text, error)."""
    with sessions_lock:
        sid = session_id
        conv_id = sessions.get(sid, {}).get("conversation_id")

    if not conv_id:
        return None, "Session or conversation not found"

    try:
        cred = DefaultAzureCredential()
        client = AIProjectClient(endpoint=ENDPOINT, credential=cred)
        all_text = []
        last_text_index = 0

        with client:
            oc = client.get_openai_client()
            stream = oc.responses.create(
                conversation=conv_id,
                extra_body={
    "agent_reference": {
        "name": WORKFLOW_NAME,
        "type": "agent_reference"
    }
},
                input=decision,
                stream=True,
                metadata={"x-ms-debug-mode-enabled": "1"},
            )

            for event in stream:
                if event.type == RESPONSE_OUTPUT_TEXT_DELTA:
                    d = getattr(event, "delta", "") or ""
                    all_text.append(d)

                elif event.type == RESPONSE_OUTPUT_TEXT_DONE:
                    t = getattr(event, "text", "") or ""
                    all_text.append(t)

                elif event.type == RESPONSE_OUTPUT_ITEM_ADDED:
                    if hasattr(event, "item") and getattr(event.item, "type", None) == "workflow_action":
                        aid = getattr(event.item, "action_id", None)
                        if aid:
                            last_text_index = len(all_text)
                            emit(
                                session_id,
                                {
                                    "type": "step",
                                    "step": aid,
                                    "status": "active",
                                    "message": f"Running {aid}...",
                                    "timestamp": _utc_ts(),
                                },
                            )

                elif event.type == RESPONSE_OUTPUT_ITEM_DONE:
                    if hasattr(event, "item") and getattr(event.item, "type", None) == "workflow_action":
                        aid = getattr(event.item, "action_id", None)
                        if aid:
                            step_text = "".join(all_text[last_text_index:]).strip()
                            print(f"[APPROVAL STEP] {aid} completed, text length: {len(step_text)}")
                            summary = _extract_step_summary(aid, step_text)
                            emit(
                                session_id,
                                {
                                    "type": "step",
                                    "step": aid,
                                    "status": "completed",
                                    "message": summary.get("summary", f"Completed {aid}"),
                                    "data": summary.get("details"),
                                    "timestamp": _utc_ts(),
                                },
                            )
                            last_text_index = len(all_text)

                elif event.type == ERROR:
                    err = getattr(event, "error", None) or str(event)
                    return None, str(err)

        cleanup_foundry_data(session_id)
        return "".join(all_text), None

    except Exception as e:
        cleanup_foundry_data(session_id)
        return None, str(e)


def _run_approval_background(session_id, decision):
    """Run approval workflow in background and write result into session."""
    print(f"[APPROVAL] Starting approval for {session_id}: {decision}")
    emit(
        session_id,
        {
            "type": "step",
            "step": "approval_submit",
            "status": "active",
            "message": f"Processing {decision}...",
            "timestamp": _utc_ts(),
        },
    )

    try:
        response_text, err = run_workflow_approval(session_id, decision)
        print(f"[APPROVAL] Workflow completed for {session_id}: err={err}, response_len={len(response_text or '')}")

        with sessions_lock:
            s = sessions.get(session_id)
            if s:
                s["status"] = "complete" if err is None else "error"
                s["approval_response"] = response_text
                s["approval_error"] = err
                print(f"[APPROVAL] Set status to {s['status']} for {session_id}")

        emit(
            session_id,
            {
                "type": "step",
                "step": "approval_submit",
                "status": "completed" if err is None else "error",
                "message": response_text or err or f"{decision} completed.",
                "timestamp": _utc_ts(),
            },
        )

    except Exception as e:
        print(f"[APPROVAL] Exception for {session_id}: {e}")
        with sessions_lock:
            s = sessions.get(session_id)
            if s:
                s["status"] = "error"
                s["approval_error"] = str(e)

        emit(
            session_id,
            {
                "type": "step",
                "step": "approval_submit",
                "status": "error",
                "message": str(e),
                "timestamp": _utc_ts(),
            },
        )


# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=str(PORTAL_DIR), static_url_path="")


@app.route("/")
def index():
    return send_from_directory(PORTAL_DIR, "index.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "invoice" not in request.files or "po" not in request.files or "grn" not in request.files:
        return Response("Missing invoice, po, or grn file", status=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    inv = request.files.get("invoice")
    po = request.files.get("po")
    grn = request.files.get("grn")

    if not inv or not po or not grn:
        return Response("Missing invoice, po, or grn file", status=400)

    prefix = f"session_{session_id}"
    parts = []
    uploaded_paths = []

    for key, f in [("invoice", inv), ("po", po), ("grn", grn)]:
        if f and f.filename:
            safe = f.filename.replace("..", "_").replace(os.sep, "_")
            path = UPLOADS_DIR / f"{prefix}_{key}_{safe}"
            f.save(path)
            uploaded_paths.append(path)

            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                parts.append(f"[Contents of {f.filename}]")

    doc_text = "\n\n".join(parts)
    if not doc_text.strip():
        return Response("Uploaded files are empty", status=400)

    with sessions_lock:
        sessions[session_id] = {
            "conversation_id": None,
            "events": [],
            "status": "running",
            "vector_store_id": None,
            "file_ids": [],
            "stream_complete": False,
        }

    emit(
        session_id,
        {
            "type": "step",
            "step": "upload",
            "status": "completed",
            "message": "Documents uploaded; uploading to Foundry and starting workflow.",
            "data": {
                "invoice": inv.filename if inv else "invoice.txt",
                "purchase_order": po.filename if po else "po.txt",
                "goods_receipt": grn.filename if grn else "grn.txt",
                "files_count": "3 documents",
            },
            "timestamp": _utc_ts(),
        },
    )

    t = threading.Thread(target=run_workflow_until_approval, args=(session_id, doc_text, uploaded_paths))
    t.daemon = True
    t.start()

    return Response(
        json.dumps({"session_id": session_id}),
        status=200,
        mimetype="application/json",
    )


@app.route("/api/progress/<session_id>")
def api_progress(session_id):
    def generate():
        idx = 0

        while True:
            with sessions_lock:
                s = sessions.get(session_id)
                if not s:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Session not found'})}\n\n"
                    return
                evs = s["events"]
                status = s["status"]

            while idx < len(evs):
                ev = evs[idx]
                idx += 1
                step = ev.get("step", "")
                st = ev.get("status", "")
                msg = ev.get("message", "")
                payload = {
                    "type": ev.get("type", "step"),
                    "step": step,
                    "status": st,
                    "message": msg,
                    "timestamp": ev.get("timestamp"),
                }

                if ev.get("data"):
                    payload["data"] = ev["data"]
                if ev.get("show_approval_buttons"):
                    payload["show_approval_buttons"] = True
                    payload["status"] = "waiting"

                print(f"[SSE] Sending: step={step}, status={st}, has_data={bool(ev.get('data'))}")
                yield f"data: {json.dumps(payload)}\n\n"

            if status == "complete" or status == "error":
                yield f"data: {json.dumps({'status': status})}\n\n"
                return

            with sessions_lock:
                s2 = sessions.get(session_id)
                if s2:
                    current_status = s2.get("status", "running")
                    stream_complete = s2.get("stream_complete", False)
                else:
                    current_status = "error"
                    stream_complete = True

            if current_status == "waiting" and stream_complete:
                print(f"[SSE] Closing - waiting status, stream complete, {idx} events sent")
                yield f"data: {json.dumps({'status': 'waiting', 'step': 'approval', 'show_approval_buttons': True})}\n\n"
                return

            if current_status in ("complete", "error"):
                yield f"data: {json.dumps({'status': current_status})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

            import time

            time.sleep(0.5)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/status/<session_id>")
def api_status(session_id):
    """Return session status and approval result for polling after Approve/Reject."""
    with sessions_lock:
        s = sessions.get(session_id)
        if not s:
            print(f"[STATUS] Session {session_id} not found")
            return Response(
                json.dumps({"status": "not_found"}),
                status=200,
                mimetype="application/json",
            )

        out = {"status": s["status"]}
        if "approval_response" in s:
            out["response"] = s.get("approval_response") or ""
        if s.get("approval_error"):
            out["error"] = s["approval_error"]

    print(f"[STATUS] Session {session_id}: {out.get('status')}")
    return Response(json.dumps(out), status=200, mimetype="application/json")


@app.route("/api/approve/<session_id>", methods=["POST"])
def api_approve(session_id):
    decision = (request.args.get("decision") or "APPROVE").upper()

    if decision not in ("APPROVE", "REJECT"):
        return Response(
            json.dumps({"error": "decision must be APPROVE or REJECT"}),
            status=400,
            mimetype="application/json",
        )

    with sessions_lock:
        if session_id not in sessions:
            return Response(json.dumps({"error": "Session not found"}), status=404, mimetype="application/json")

        if sessions[session_id]["status"] != "waiting":
            return Response(
                json.dumps({"error": "Session not waiting for approval"}),
                status=400,
                mimetype="application/json",
            )

        sessions[session_id]["status"] = "approving"

    t = threading.Thread(target=_run_approval_background, args=(session_id, decision))
    t.daemon = True
    t.start()

    return Response(
        json.dumps({"ok": True, "status": "processing"}),
        status=202,
        mimetype="application/json",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Invoice Portal: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
