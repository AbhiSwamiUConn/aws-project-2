import json
import csv
import boto3
import os
import urllib.parse
import re

s3 = boto3.client("s3")
comprehend = boto3.client("comprehend")

QUARANTINE_BUCKET = os.environ.get("QUARANTINE_BUCKET")

VALID_LANGS = {"en", "es", "fr", "de", "it", "pt", "ar", "hi", "ja", "ko", "zh", "zh-TW"}


def normalize_language(lang):
    if not lang:
        return "en"

    lang = lang.lower()

    mapping = {
        "english": "en",
        "en-us": "en",
        "en-gb": "en",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "japanese": "ja",
        "korean": "ko",
        "chinese": "zh",
        "zh-cn": "zh",
        "zh-tw": "zh-TW",
    }

    normalized = mapping.get(lang, lang)

    if normalized not in VALID_LANGS:
        return "en"

    return normalized


def redact_pii(text, language_code):
    """
    Redact PII from extracted unstructured text (SSNs, addresses, etc.)
    so downstream logs/LLM calls reduce exposure.

    NOTE: This demo uses Comprehend PII; production should also consider
    data classification, KMS, access controls, and audit requirements.
    """
    if not text:
        return text

    try:
        response = comprehend.detect_pii_entities(Text=text, LanguageCode=language_code)

        entities = response.get("Entities", [])
        redacted_text = text

        # Replace from end to avoid index shifting
        for entity in sorted(entities, key=lambda x: x["BeginOffset"], reverse=True):
            start = entity["BeginOffset"]
            end = entity["EndOffset"]
            redacted_text = redacted_text[:start] + "[REDACTED]" + redacted_text[end:]

        return redacted_text

    except Exception as e:
        print(f"PII detection failed: {e}")
        return text  # fallback without breaking pipeline


def parse_csv(content):
    records = []
    reader = csv.DictReader(content.splitlines())
    for row in reader:
        records.append(dict(row))
    return records


def parse_json(content):
    data = json.loads(content)
    return data.get("records", [])


def load_file_from_s3(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj["Body"].read().decode("utf-8")

    if key.endswith(".csv"):
        return parse_csv(content)
    elif key.endswith(".json"):
        return parse_json(content)
    else:
        raise ValueError("Unsupported file format (expected .json or .csv)")


def quarantine_file(bucket, key, reason):
    if not QUARANTINE_BUCKET:
        return

    dest_key = f"quarantine/{key}"
    print(f"Quarantining file {key} due to: {reason}")

    s3.copy_object(
        Bucket=QUARANTINE_BUCKET, CopySource={"Bucket": bucket, "Key": key}, Key=dest_key
    )


def _extract_entities_from_record(record):
    """
    "Extraction" stage:
    - Pull structured fields if present
    - Derive missing pieces from document text via simple regex heuristics (demo)
    """
    doc_text = record.get("document_text") or record.get("feedback_text") or ""

    # Normalize SSN: keep only last4 if present
    ssn_match = re.search(r"\b(\d{3}-\d{2}-\d{4})\b", doc_text)
    ssn_last4 = ssn_match.group(1)[-4:] if ssn_match else (record.get("ssn_last4") or "")

    # Extremely lightweight heuristics for demo inputs
    entities = {
        "name": record.get("name") or "",
        "address": record.get("address") or "",
        "annual_wages_claimed": _to_number(record.get("annual_wages_claimed") or record.get("annual_wages") or ""),
        "annual_wages_w2": _to_number(record.get("w2_wages") or ""),
        "annual_wages_tax_return": _to_number(record.get("tax_return_wages") or ""),
        "debts_total": _to_number(record.get("debts_total") or record.get("available_debts") or ""),
        "home_value": _to_number(record.get("home_value") or ""),
        "loan_requested": _to_number(record.get("loan_requested") or ""),
        "ssn_last4": ssn_last4,
    }

    # Copy optional home info fields
    if record.get("home_address"):
        entities["home_address"] = record["home_address"]

    return doc_text, entities


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("$", "").replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def lambda_handler(event, context):
    """
    Supports EventBridge S3 "Object Created" events.
    Output schema:
      { "records": [ { application_id, extracted_text, entities, claimed } ] }
    """
    print("Received event:", json.dumps(event))

    try:
        bucket = event["detail"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(event["detail"]["object"]["key"])

        records = load_file_from_s3(bucket, key)

    except Exception as e:
        print(f"Failed to load file: {e}")
        # best-effort quarantine
        try:
            quarantine_file(bucket, key, str(e))
        except Exception:
            pass
        raise

    cleaned_records = []

    for record in records:
        try:
            lang = normalize_language(record.get("language"))
            doc_text, entities = _extract_entities_from_record(record)

            redacted_text = redact_pii(doc_text, lang)

            application_id = record.get("application_id") or record.get("feedback_id") or "unknown"

            # "claimed" is the applicant-stated values in the application form (demo)
            claimed = {
                "annual_wages": entities.get("annual_wages_claimed"),
                "debts_total": entities.get("debts_total"),
                "loan_requested": entities.get("loan_requested"),
            }

            cleaned_records.append(
                {
                    "application_id": application_id,
                    "language": lang,
                    "extracted_text": redacted_text,
                    "entities": entities,
                    "claimed": claimed,
                }
            )

        except Exception as e:
            print(f"Skipping bad record: {e}")
            continue

    if not cleaned_records:
        raise ValueError("No valid application records found after processing")

    return {"records": cleaned_records}
