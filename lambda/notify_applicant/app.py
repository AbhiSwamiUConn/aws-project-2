import boto3
import json
import os

ses = boto3.client("ses")

FROM_EMAIL = os.environ.get("FROM_EMAIL", "no-reply@example.com")
DEFAULT_TO_EMAIL = os.environ.get("DEFAULT_TO_EMAIL", "applicant@example.com")


def lambda_handler(event, context):
    """
    Send an SES email notifying the applicant of their application status.

    Input: the object returned by PersistResultFunction (or similar),
    containing application_id and final_status.
    """
    print("notify_applicant event:", json.dumps(event))

    application_id = event.get("application_id") or event.get("feedback_id") or "unknown"
    final_status = event.get("final_status", "UNKNOWN")
    to_email = event.get("applicant_email") or DEFAULT_TO_EMAIL

    subject = f"Mortgage application status: {final_status}"
    body = (
        f"Your mortgage application ({application_id}) has been processed.\n\n"
        f"Status: {final_status}\n\n"
        "If your application was flagged for human review, a reviewer will contact you if additional information is needed."
    )

    # Note: SES requires verified identities (sender and sometimes recipient) in many accounts/regions.
    resp = ses.send_email(
        Source=FROM_EMAIL,
        Destination={"ToAddresses": [to_email]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )

    return {"ok": True, "message_id": resp.get("MessageId"), "to": to_email}
