"""Copy the model/tracing API keys from .env into the v2 Secrets Manager secret pharmassist/v2/app-keys.

Run from the repository root:
    AWS_PROFILE=pharmassist .venv/bin/python deploy/aws/v2/put_secrets.py [--refresh-instances]

The secret is one JSON document with exactly the keys OPENAI_API_KEY, ANTHROPIC_API_KEY and
LANGSMITH_API_KEY (ECS secret injection needs every key to exist, so a key missing from .env is written
as an empty string). Values are never printed: the output names the secret and which keys were set.
The API instances read the secret at boot and the worker at task start, so after a change either rerun
deploy.sh or pass --refresh-instances (rolling replacement of the EC2 instances, one at a time).
The secret itself is created by the stack (deploy/aws/v2/template.yaml); run deploy.sh first if it does
not exist yet, or pass --create to create it ahead of the stack (CloudFormation then adopts nothing: the
stack would fail on a name clash, so --create is for the case where the stack will never own it).
"""

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[3]
KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY")
TAGS = [{"Key": "Project", "Value": "pharmassist"}]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", default="pharmassist")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--refresh-instances", action="store_true", help="start an instance refresh of the API Auto Scaling group")
    ap.add_argument("--create", action="store_true", help="create the secret if the stack has not (see docstring)")
    args = ap.parse_args()

    env = dotenv_values(args.env_file)
    payload = {k: (env.get(k) or "") for k in KEYS}
    name = f"{args.app}/v2/app-keys"
    sm = boto3.client("secretsmanager")
    try:
        sm.put_secret_value(SecretId=name, SecretString=json.dumps(payload))
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        if not args.create:
            print(f"{name}: does not exist yet; run deploy/aws/v2/deploy.sh first (or pass --create)", file=sys.stderr)
            sys.exit(1)
        sm.create_secret(Name=name, SecretString=json.dumps(payload), Tags=TAGS)
        print(f"{name}: created")
    for k in KEYS:
        print(f"{name}: {k} {'set' if payload[k] else 'EMPTY (not in .env)'}")

    if args.refresh_instances:
        asg = boto3.client("autoscaling")
        r = asg.start_instance_refresh(AutoScalingGroupName=f"{args.app}-v2-api",
                                       Preferences={"MinHealthyPercentage": 50, "InstanceWarmup": 240})
        print(f"instance refresh started: {r['InstanceRefreshId']} (new instances read the new keys at boot)")
    else:
        print("note: running instances keep the old values until replaced (deploy.sh or --refresh-instances)")


if __name__ == "__main__":
    main()
