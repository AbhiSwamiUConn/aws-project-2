import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["RESULTS_TABLE"])


def to_dynamo_safe(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo_safe(v) for v in value]
    return value


def lambda_handler(event, context):
    """
    Persist the final recommendation/status for a mortgage application.

    Expected input keys (from state machine):
      - application_id
      - final_status
      - recommendation (optional)
      - confidence (optional)
      - credit_score (optional)
      - flags (optional)
      - explanation (optional)
      - review_id (optional)
    """
    now = datetime.now(timezone.utc).isoformat()

    application_id = event.get("application_id") or event.get("feedback_id") or "unknown"

    item = {
        "application_id": application_id,
        "final_status": event.get("final_status", "UNKNOWN"),
        "recommendation": event.get("recommendation"),
        "confidence": event.get("confidence"),
        "credit_score": event.get("credit_score"),
        "flags": event.get("flags") or [],
        "explanation": event.get("explanation") or "",
        "review_id": event.get("review_id"),
        "updated_at": now,
    }

    table.put_item(Item=to_dynamo_safe(item))

    return {"ok": True, "application_id": application_id}
