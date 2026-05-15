import boto3
import json
import os
import re

bedrock = boto3.client("bedrock-runtime")
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model did not return JSON")
    return json.loads(text[start : end + 1])


def _rule_based_reasoning(payload):
    """
    Deterministic fallback reasoning so the demo works without a live model.
    Flags mismatches between claimed income and tax/W2 values.
    """
    entities = payload.get("entities", {}) or {}
    claimed = payload.get("claimed", {}) or {}

    claimed_income = claimed.get("annual_wages") or entities.get("annual_wages_claimed")
    tax_income = entities.get("annual_wages_tax_return")
    w2_income = entities.get("annual_wages_w2")

    flags = []
    confidence = 0.85
    recommendation = "APPROVE"

    # Example mismatch check from prompt
    if claimed_income and tax_income and claimed_income > (tax_income * 1.10):
        flags.append(
            f"Income mismatch: applicant claims ${claimed_income:,.0f} but tax return shows ${tax_income:,.0f}."
        )
        recommendation = "HUMAN_REVIEW"
        confidence = 0.75

    if claimed_income and w2_income and claimed_income > (w2_income * 1.10):
        flags.append(
            f"Income mismatch: applicant claims ${claimed_income:,.0f} but W2 shows ${w2_income:,.0f}."
        )
        recommendation = "HUMAN_REVIEW"
        confidence = min(confidence, 0.75)

    explanation = "No material inconsistencies detected."
    if flags:
        explanation = " ".join(flags) + " Flag for human review."

    return {
        "application_id": payload.get("application_id", "unknown"),
        "entities": entities,
        "claimed": claimed,
        "flags": flags,
        "recommendation": recommendation,
        "confidence": confidence,
        "explanation": explanation,
        # keep for downstream steps
        "extracted_text": payload.get("extracted_text", ""),
        "applicant_email": payload.get("applicant_email", ""),
    }


def build_prompt(record):
    return f"""
You are a mortgage application reviewer.

Return ONLY valid JSON with this schema:
{{
  "application_id": string,
  "recommendation": "APPROVE" | "DENY" | "HUMAN_REVIEW",
  "confidence": number,
  "flags": [string],
  "explanation": string
}}

Rules:
- Compare applicant-claimed values vs extracted supporting documents (W2/tax returns).
- Example: "The applicant claims $120k income, but tax returns show $95k. Flag for human review."
- Confidence must be between 0 and 1.
- Do not use markdown fences.

Extracted application payload:
{json.dumps(record, ensure_ascii=False)}
""".strip()


def lambda_handler(event, context):
    # First produce a deterministic result, then optionally let Bedrock override/enhance.
    base = _rule_based_reasoning(event)

    # Best-effort Bedrock call; if it fails, return the deterministic reasoning.
    try:
        prompt = build_prompt(event)

        response = bedrock.converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0, "maxTokens": 500},
        )

        text = "".join(part.get("text", "") for part in response["output"]["message"]["content"])
        parsed = extract_json(text)

        # Merge: model output + keep original entities/claimed/text for downstream steps.
        return {
            "application_id": parsed.get("application_id", base["application_id"]),
            "recommendation": parsed.get("recommendation", base["recommendation"]),
            "confidence": parsed.get("confidence", base["confidence"]),
            "flags": parsed.get("flags", base["flags"]),
            "explanation": parsed.get("explanation", base["explanation"]),
            "entities": base["entities"],
            "claimed": base["claimed"],
            "extracted_text": base["extracted_text"],
            "applicant_email": base["applicant_email"],
        }
    except Exception as e:
        print(f"Bedrock call failed, using rule-based reasoning. Error: {e}")
        return base
