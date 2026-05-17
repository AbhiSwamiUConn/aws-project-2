import boto3
import json
import os
from botocore.exceptions import ClientError

ses = boto3.client("ses")

FROM_EMAIL = os.environ.get("FROM_EMAIL")
DEFAULT_TO_EMAIL = os.environ.get("DEFAULT_TO_EMAIL")


def lambda_handler(event, context):
    """
    Send an SES email notifying the applicant of their application status.
    """
    print("notify_applicant event:", json.dumps(event))

    application_id = event.get("application_id") or event.get("feedback_id") or "unknown"
    final_status = event.get("final_status", "UNKNOWN")
    to_email = event.get("applicant_email") or DEFAULT_TO_EMAIL

    subject = f"Mortgage application status: {final_status}"
    body = (
        f"Your mortgage application ({application_id}) has been processed.\n\n"
        f"Status: {final_status}\n"
        f"Recommendation: {event.get('recommendation', 'N/A')}\n"
        f"Confidence: {event.get('confidence', 'N/A')}\n"
        f"Credit Score: {event.get('credit_score', 'N/A')}\n\n"
        f"Explanation: {event.get('explanation', 'No explanation available.')}\n\n"
        "If your application was flagged for human review, a reviewer will contact you if additional information is needed."
    )

    try:
        resp = ses.send_email(
            Source=FROM_EMAIL,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
    except ClientError as e:
        print(f"SES send failed: {e}")
        raise

    return {
        "ok": True,
        "message_id": resp.get("MessageId"),
        "to": to_email,
        "application_id": application_id,
        "final_status": final_status,
    }
