import csv
import io
import json
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

        for entity in sorted(entities, key=lambda x: x["BeginOffset"], reverse=True):
            start = entity["BeginOffset"]
            end = entity["EndOffset"]
            redacted_text = redacted_text[:start] + "[REDACTED]" + redacted_text[end:]

        return redacted_text

    except Exception as e:
        print(f"PII detection failed: {e}")
        return text


def normalize_record_keys(record):
    normalized = {}
    for key, value in record.items():
        cleaned_key = str(key).strip()
        normalized[cleaned_key] = value.strip() if isinstance(value, str) else value
    return normalized


def parse_csv(content):
    records = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        cleaned = normalize_record_keys(dict(row))
        if any(value not in (None, "") for value in cleaned.values()):
            records.append(cleaned)
    return records


def parse_json(content):
    data = json.loads(content)

    if isinstance(data, list):
        return [normalize_record_keys(record) for record in data if isinstance(record, dict)]

    if isinstance(data, dict):
        if isinstance(data.get("records"), list):
            return [normalize_record_keys(record) for record in data["records"] if isinstance(record, dict)]
        return [normalize_record_keys(data)]

    raise ValueError("Unsupported JSON payload shape")


def load_file_from_s3(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj["Body"].read().decode("utf-8")
    normalized_key = key.lower()

    if normalized_key.endswith(".csv"):
        return parse_csv(content)
    if normalized_key.endswith(".json"):
        return parse_json(content)

    stripped = content.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json(content)

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

    ssn_match = re.search(r"\b(\d{3}-\d{2}-\d{4})\b", doc_text)
    ssn_last4 = ssn_match.group(1)[-4:] if ssn_match else (record.get("ssn_last4") or "")

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

    if record.get("home_address"):
        entities["home_address"] = record["home_address"]

    if record.get("applicant_email"):
        entities["applicant_email"] = record["applicant_email"]

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

    bucket = None
    key = None

    try:
        bucket = event["detail"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(event["detail"]["object"]["key"])

        records = load_file_from_s3(bucket, key)

    except Exception as e:
        print(f"Failed to load file: {e}")
        try:
            if bucket and key:
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
                    "applicant_email":  record.get("applicant_email") or entities.get("applicant_email"),
                    "source_bucket": bucket,
                    "source_key": key,
                }
            )

        except Exception as e:
            print(f"Skipping bad record: {e}")
            continue

    if not cleaned_records:
        raise ValueError("No valid application records found after processing")

    return {"records": cleaned_records}
