# aws-project-2

Mortgage application reviewer (serverless reference implementation)

Flow:
1) Ingestion: applicant uploads documents (JSON/CSV demo files) to S3 `incoming/` prefix
2) Extraction: Lambda extracts & normalizes applicant entities (name, address, wages, debts, W2 wages, SSN, home info, loan requested)
3) Intelligent reasoning: Bedrock-style reasoning step compares extracted vs application and calls a stub credit bureau API (random score 440-780)
4) Completion: Step Functions persists final recommendation and sends SES email notification

Accepted input formats:
- CSV with one row per application record
- JSON object with a top-level `records` array
- JSON array of record objects
- Single JSON object representing one application

Supported record fields:
- `application_id`
- `language`
- `name`
- `address`
- `annual_wages_claimed`
- `tax_return_wages`
- `w2_wages`
- `debts_total`
- `home_value`
- `loan_requested`
- `document_text`
- `applicant_email`
- optional `ssn_last4`, `home_address`

Human review behavior:
- Applications route to human review when:
  - the reasoning step returns `HUMAN_REVIEW`
  - confidence is below the configured threshold
  - credit score is below 580
- Human review uses a Step Functions task token callback pattern
- Review completion must happen before the state machine wait task expires

SES requirements:
- `NotificationFromEmail` must be a verified SES identity in the deployment region
- In SES sandbox, recipients may also need to be verified
- Replace the default placeholder emails before deployment

Prereqs:
- Install AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- Configure AWS credentials (e.g., `aws configure`)

# paste the following into a terminal
python3 -m venv venv  
source venv/bin/activate  
pip install -r requirements.txt  
sam build  
sam deploy 

# Submit application docs for review (demo JSON/CSV)
aws s3 cp {json_or_csv_file} s3://{application_bucket_name}/incoming/{json_or_csv_file}

# Optional: Manual review callback (if workflow creates a human review task)
# Select the review id from the dynamodb reviews table then:
aws lambda invoke \
  --function-name {submit_review_lambda_function_name} \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "review_id": "insert_id_here",
    "decision": "APPROVED",
    "reviewer": "insert_email_address",
    "notes": "optional notes"
  }' \
  response.json

# Example input files in repo:
# - example_inputs.csv
# - ex_human_needed.json
