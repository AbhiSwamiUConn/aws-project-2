# aws-project-2

Mortgage application reviewer (serverless reference implementation)

Flow:
1) Ingestion: applicant uploads documents (JSON/CSV demo files) to S3 `incoming/` prefix
2) Extraction: Lambda extracts & normalizes applicant entities (name, address, wages, debts, W2 wages, SSN, home info, loan requested)
3) Intelligent reasoning: Bedrock-style reasoning step compares extracted vs application and calls a stub credit bureau API (random score 440-780)
4) Completion: Step Functions persists final recommendation and sends SES email notification

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
    "reviewer": "insert_email_address"
  }' \
  response.json

# Example input files in repo:
# - example_inputs.csv
# - ex_human_needed.json
