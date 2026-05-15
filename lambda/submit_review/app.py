import boto3
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from botocore.exceptions import ClientError

ddb = boto3.resource("dynamodb")
sfn = boto3.client("stepfunctions")
table = ddb.Table(os.environ["REVIEWS_TABLE"])

VALID_DECISIONS = {"APPROVED", "DENIED", "HUMAN_REVIEW"}


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
    """
    review_id = event.get("review_id") or event.get("pathParameters", {}).get("review_id")
    decision = event.get("decision")
    reviewer = event.get("reviewer")
    notes = event.get("notes")

    if not review_id:
        raise ValueError("review_id is required")

    if decision not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(VALID_DECISIONS)}")

    item = table.get_item(Key={"review_id": review_id}).get("Item")
    if not item:
        raise ValueError("Review record not found")

    task_token = item["task_token"]
    now = datetime.now(timezone.utc).isoformat()

    payload = item.get("payload") or {}
    application_id = payload.get("application_id") or payload.get("feedback_id") or "unknown"

    output = {
        "application_id": application_id,
        "final_status": decision,
        "review_id": review_id,
        "reviewed_at": now,
        "reviewer": reviewer,
        "notes": notes,
    }

    try:
        sfn.send_task_success(taskToken=task_token, output=json.dumps(json_safe(output)))
        review_status = "COMPLETED"
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code in {"TaskTimedOut", "TaskDoesNotExist", "InvalidToken"}:
            review_status = "CALLBACK_FAILED"
            output["callback_error"] = error_code
        else:
            raise

    table.update_item(
        Key={"review_id": review_id},
        UpdateExpression=(
            "SET #s = :s, reviewed_at = :r, decision = :d, reviewer = :rev, notes = :n, callback_error = :ce"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": review_status,
            ":r": now,
            ":d": decision,
            ":rev": reviewer,
            ":n": notes,
            ":ce": output.get("callback_error"),
        },
    )

    return {"ok": True, "review_id": review_id, "status": review_status}
