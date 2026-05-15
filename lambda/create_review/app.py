import boto3
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["REVIEWS_TABLE"])


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
    Human review handoff for mortgage application decisions.

    Input (from Step Functions waitForTaskToken):
      { task_token, feedback: <application payload> }

    NOTE: input key is still named "feedback" for compatibility with the existing workflow,
    but it contains a mortgage application payload (application_id, entities, flags, etc.).
    """
    task_token = event["task_token"]
    payload = to_dynamo_safe(event["feedback"])

    review_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    item = {
        "review_id": review_id,
        "task_token": task_token,
        "status": "PENDING",
        "created_at": now,
        "payload": payload,
    }

    table.put_item(Item=item)

    return {
        "review_id": review_id,
        "status": "PENDING",
        "application_id": payload.get("application_id", "unknown"),
    }
