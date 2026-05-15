import boto3
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

ddb = boto3.resource("dynamodb")
sfn = boto3.client("stepfunctions")
table = ddb.Table(os.environ["REVIEWS_TABLE"])


def json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


def lambda_handler(event, context):
    """
    Manual completion of a human review task.

    Expected payload:
      {
        "review_id": "...",
        "decision": "APPROVED" | "DENIED" | "HUMAN_REVIEW",
        "reviewer": "email@domain" (optional),
        "notes": "..." (optional)
      }
    """
    review_id = (event.get("review_id") or event.get("pathParameters", {}).get("review_id"))
    decision = event["decision"]
    reviewer = event.get("reviewer")
    notes = event.get("notes")

    item = table.get_item(Key={"review_id": review_id}).get("Item")
    if not item:
        raise ValueError("Review record not found")

    task_token = item["task_token"]
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"review_id": review_id},
        UpdateExpression="SET #s = :s, reviewed_at = :r, decision = :d, reviewer = :rev, notes = :n",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "COMPLETED",
            ":r": now,
            ":d": decision,
            ":rev": reviewer,
            ":n": notes,
        },
    )

    payload = item.get("payload") or {}
    application_id = (payload.get("application_id") or payload.get("feedback_id") or "unknown")

    output = {
        "application_id": application_id,
        "final_status": decision,
        "review_id": review_id,
        "reviewed_at": now,
    }

    sfn.send_task_success(taskToken=task_token, output=json.dumps(json_safe(output)))

    return {"ok": True, "review_id": review_id}
