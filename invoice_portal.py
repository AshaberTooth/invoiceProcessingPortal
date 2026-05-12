"""
Invoice Processing Portal
Compatible with OLD azure-ai-projects SDK
"""

import os
import sys
import json
import uuid
import time
import logging
import threading

from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# Load Environment Variables
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / "azure.env")

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Windows UTF-8 Fix
# -----------------------------------------------------------------------------

if sys.platform == "win32":

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

try:

    from flask import (
        Flask,
        request,
        Response,
        send_from_directory
    )

    from azure.identity import (
        DefaultAzureCredential
    )

    from azure.ai.projects import (
        AIProjectClient
    )

    logger.info("Imports successful")

except Exception:

    import traceback

    logger.error("IMPORT FAILURE")

    traceback.print_exc()

    raise

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

PORTAL_DIR = BASE_DIR / "portal"

UPLOADS_DIR = BASE_DIR / "uploads"

UPLOADS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------

PORT = int(
    os.environ.get("PORT", 8000)
)

WORKFLOW_NAME = (
    "Invoice-Processing-Workflow"
)

PROJECT_ENDPOINT = os.environ.get(
    "AZURE_PROJECT_ENDPOINT"
)

SUBSCRIPTION_ID = os.environ.get(
    "AZURE_SUBSCRIPTION_ID"
)

RESOURCE_GROUP = os.environ.get(
    "AZURE_RESOURCE_GROUP"
)

PROJECT_NAME = os.environ.get(
    "AZURE_PROJECT_NAME"
)

# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

missing = []

if not PROJECT_ENDPOINT:
    missing.append("AZURE_PROJECT_ENDPOINT")

if not SUBSCRIPTION_ID:
    missing.append("AZURE_SUBSCRIPTION_ID")

if not RESOURCE_GROUP:
    missing.append("AZURE_RESOURCE_GROUP")

if not PROJECT_NAME:
    missing.append("AZURE_PROJECT_NAME")

if missing:

    raise Exception(
        "Missing environment variables: "
        + ", ".join(missing)
    )

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logger.info(
    f"PROJECT_ENDPOINT: {PROJECT_ENDPOINT}"
)

logger.info(
    f"SUBSCRIPTION_ID: {SUBSCRIPTION_ID}"
)

logger.info(
    f"RESOURCE_GROUP: {RESOURCE_GROUP}"
)

logger.info(
    f"PROJECT_NAME: {PROJECT_NAME}"
)

# -----------------------------------------------------------------------------
# Flask App
# -----------------------------------------------------------------------------

app = Flask(
    __name__,
    static_folder=str(PORTAL_DIR),
    static_url_path=""
)

# -----------------------------------------------------------------------------
# Session Store
# -----------------------------------------------------------------------------

sessions = {}

sessions_lock = threading.Lock()

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def utc_ts():

    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

def emit(
    session_id,
    obj
):

    with sessions_lock:

        if session_id in sessions:

            sessions[session_id][
                "events"
            ].append(obj)

# -----------------------------------------------------------------------------
# Create AI Project Client
# -----------------------------------------------------------------------------

def get_project_client():

    credential = DefaultAzureCredential()

    client = AIProjectClient(
        endpoint=PROJECT_ENDPOINT,
        subscription_id=SUBSCRIPTION_ID,
        resource_group_name=RESOURCE_GROUP,
        project_name=PROJECT_NAME,
        credential=credential
    )

    return client

# -----------------------------------------------------------------------------
# Workflow Runner
# -----------------------------------------------------------------------------

def run_workflow_until_approval(
    session_id,
    doc_text,
    uploaded_paths
):

    try:

        logger.info(
            "Starting workflow"
        )

        client = get_project_client()

        with client:

            logger.info(
                "Getting Azure OpenAI client"
            )

            oc = (
                client.inference.get_azure_openai_client()
            )

            logger.info(
                "Azure OpenAI client acquired"
            )

            # -------------------------------------------------------------
            # Upload Files
            # -------------------------------------------------------------

            emit(session_id, {
                "type": "step",
                "step": "upload",
                "status": "active",
                "message": "Uploading documents to Azure Foundry",
                "timestamp": utc_ts()
            })

            uploaded_file_ids = []

            for path in uploaded_paths:

                logger.info(
                    f"Uploading file: {path}"
                )

                with open(path, "rb") as f:

                    uploaded = oc.files.create(
                        file=f,
                        purpose="assistants"
                    )

                uploaded_file_ids.append(
                    uploaded.id
                )

                logger.info(
                    f"Uploaded file id: {uploaded.id}"
                )

            emit(session_id, {
                "type": "step",
                "step": "upload",
                "status": "completed",
                "message": "Documents uploaded successfully",
                "timestamp": utc_ts()
            })

            # -------------------------------------------------------------
            # Create Vector Store
            # -------------------------------------------------------------

            emit(session_id, {
                "type": "step",
                "step": "vector_store",
                "status": "active",
                "message": "Creating vector store",
                "timestamp": utc_ts()
            })

            vector_store = oc.vector_stores.create(
                name=f"InvoiceSession-{session_id}"
            )

            vector_store_id = vector_store.id

            logger.info(
                f"Vector store created: {vector_store_id}"
            )

            for path in uploaded_paths:

                with open(path, "rb") as f:

                    oc.vector_stores.files.upload_and_poll(
                        vector_store_id=vector_store_id,
                        file=f
                    )

            emit(session_id, {
                "type": "step",
                "step": "vector_store",
                "status": "completed",
                "message": "Vector store indexing completed",
                "timestamp": utc_ts()
            })

            # -------------------------------------------------------------
            # Store Session Data
            # -------------------------------------------------------------

            with sessions_lock:

                sessions[session_id][
                    "vector_store_id"
                ] = vector_store_id

                sessions[session_id][
                    "file_ids"
                ] = uploaded_file_ids

            # -------------------------------------------------------------
            # Create Conversation
            # -------------------------------------------------------------

            conversation = oc.conversations.create()

            logger.info(
                f"Conversation created: {conversation.id}"
            )

            with sessions_lock:

                sessions[session_id][
                    "conversation_id"
                ] = conversation.id

            # -------------------------------------------------------------
            # Execute Workflow
            # -------------------------------------------------------------

            emit(session_id, {
                "type": "step",
                "step": "workflow",
                "status": "active",
                "message": "Executing invoice workflow",
                "timestamp": utc_ts()
            })

            stream = oc.responses.create(
                conversation=conversation.id,
                input=doc_text,
                stream=True,
                extra_body={
                    "agent": {
                        "name": WORKFLOW_NAME,
                        "type": "agent_reference"
                    }
                }
            )

            for event in stream:

                try:

                    logger.info(
                        f"Event Type: {event.type}"
                    )

                    if (
                        event.type ==
                        "response.output_item.added"
                    ):

                        if hasattr(event, "item"):

                            action_id = getattr(
                                event.item,
                                "action_id",
                                "workflow"
                            )

                            emit(session_id, {
                                "type": "step",
                                "step": action_id,
                                "status": "active",
                                "message": f"{action_id} started",
                                "timestamp": utc_ts()
                            })

                    elif (
                        event.type ==
                        "response.output_item.done"
                    ):

                        if hasattr(event, "item"):

                            action_id = getattr(
                                event.item,
                                "action_id",
                                "workflow"
                            )

                            emit(session_id, {
                                "type": "step",
                                "step": action_id,
                                "status": "completed",
                                "message": f"{action_id} completed",
                                "timestamp": utc_ts()
                            })

                except Exception:

                    logger.exception(
                        "Event processing failed"
                    )

            logger.info(
                "Workflow completed"
            )

            with sessions_lock:

                sessions[session_id][
                    "status"
                ] = "waiting"

            emit(session_id, {
                "type": "step",
                "step": "approval",
                "status": "waiting",
                "message": "Approve or Reject invoice",
                "show_approval_buttons": True,
                "timestamp": utc_ts()
            })

    except Exception:

        logger.exception(
            "Workflow failed"
        )

        emit(session_id, {
            "type": "step",
            "step": "error",
            "status": "error",
            "message": "Workflow failed",
            "timestamp": utc_ts()
        })

        with sessions_lock:

            if session_id in sessions:

                sessions[session_id][
                    "status"
                ] = "error"

# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route("/")
def index():

    return send_from_directory(
        PORTAL_DIR,
        "index.html"
    )

@app.route("/health")
def health():

    return {
        "status": "healthy"
    }

@app.route(
    "/api/upload",
    methods=["POST"]
)
def api_upload():

    try:

        if (
            "invoice" not in request.files or
            "po" not in request.files or
            "grn" not in request.files
        ):

            return Response(
                "Missing files",
                status=400
            )

        session_id = (
            datetime.now()
            .strftime("%Y%m%d_%H%M%S")
            + "_"
            + uuid.uuid4().hex[:8]
        )

        uploaded_paths = []

        doc_parts = []

        for key in [
            "invoice",
            "po",
            "grn"
        ]:

            f = request.files[key]

            safe_name = (
                f.filename
                .replace("/", "_")
                .replace("\\", "_")
            )

            path = (
                UPLOADS_DIR /
                f"{session_id}_{safe_name}"
            )

            f.save(path)

            uploaded_paths.append(path)

            try:

                content = path.read_text(
                    encoding="utf-8",
                    errors="replace"
                )

            except Exception:

                content = (
                    f"[Binary File: {safe_name}]"
                )

            doc_parts.append(content)

        doc_text = "\n\n".join(doc_parts)

        with sessions_lock:

            sessions[session_id] = {
                "events": [],
                "status": "running",
                "conversation_id": None,
                "vector_store_id": None,
                "file_ids": []
            }

        thread = threading.Thread(
            target=run_workflow_until_approval,
            args=(
                session_id,
                doc_text,
                uploaded_paths
            )
        )

        thread.daemon = True

        thread.start()

        return Response(
            json.dumps({
                "session_id": session_id
            }),
            mimetype="application/json"
        )

    except Exception:

        logger.exception(
            "Upload failed"
        )

        return Response(
            json.dumps({
                "error": "Upload failed"
            }),
            status=500,
            mimetype="application/json"
        )

@app.route(
    "/api/progress/<session_id>"
)
def api_progress(session_id):

    def generate():

        idx = 0

        while True:

            with sessions_lock:

                session = sessions.get(
                    session_id
                )

            if not session:

                yield (
                    f"data: "
                    f"{json.dumps({'error':'Session not found'})}\n\n"
                )

                return

            events = session["events"]

            while idx < len(events):

                event = events[idx]

                idx += 1

                yield (
                    f"data: "
                    f"{json.dumps(event)}\n\n"
                )

            if session["status"] in [
                "complete",
                "error"
            ]:

                yield (
                    f"data: "
                    f"{json.dumps({'status': session['status']})}\n\n"
                )

                return

            time.sleep(1)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":

    logger.info(
        f"Starting server on port {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )