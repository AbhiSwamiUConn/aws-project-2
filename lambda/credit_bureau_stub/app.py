import json
import random
from datetime import datetime, timezone


def lambda_handler(event, context):
    """
    Stubbed "external credit bureau API" integration.

    In the intended architecture, a Bedrock Agent would call an external service
    via AgentCore Gateway. For this repo, we model it as a Lambda that returns
    a random credit score between 440-780 each call.
    """
    score = random.randint(440, 780)

    # Minimal log-friendly payload (avoid full PII)
    audit = {
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "name": event.get("name"),
        "ssn_last4": event.get("ssn_last4"),
        "credit_score": score,
    }
    print("credit_bureau_stub:", json.dumps(audit))

    return {"credit_score": score, "queried_at": audit["queried_at"]}
