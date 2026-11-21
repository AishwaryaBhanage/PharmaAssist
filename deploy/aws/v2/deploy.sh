#!/usr/bin/env bash
# Build both images, push them to ECR and deploy the v2 stack, then run the database migration. Run from
# the repository root (see deploy/aws/v2/README.md for the whole sequence):
#   aws cloudformation deploy ... bootstrap.yaml     (once, as an account administrator)
#   deploy/aws/v2/request_cert.sh [--wait]           (once; DNS CNAME at GoDaddy; HTTPS needs it ISSUED)
#   deploy/aws/v2/put_secrets.py                     (once, and whenever a key changes)
#   deploy/aws/v2/deploy.sh                          (this; ~20 min the first time: RDS + ElastiCache)
#   deploy/aws/v2/seed-users.sh                      (once)
# Environment knobs: CERTIFICATE_ARN (else auto-detected for HOST_NAME), HOST_NAME, SUBNET_AZS
# (default us-east-1a,us-east-1b), SKIP_BUILD=1 (reuse the images already in the stack), APP_IMAGE and/or
# INGEST_IMAGE (reuse a given image URI and build only the other one), SKIP_MIGRATE=1,
# INSTANCE_TYPE, DESIRED_CAPACITY, DB_INSTANCE_CLASS, CACHE_NODE_TYPE, CACHE_ENGINE_VERSION, LANGSMITH_TRACING,
# WORKER_MIN_COUNT (ingestion tasks kept warm; default 1).
# Runs as the pharmassist-deployer role (AWS_PROFILE=pharmassist); every resource is tagged Project=pharmassist.
set -euo pipefail
. "$(dirname "$0")/common.sh"
[ -f deploy/aws/v2/template.yaml ] || { echo "run from the repository root" >&2; exit 1; }

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "deploying $STACK as $(aws sts get-caller-identity --query Arn --output text) in $REGION"
REGISTRY=${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com
TAG=$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)
EXEC_ROLE=arn:aws:iam::${ACCOUNT}:role/${APP}-cfn-exec
BUCKET=${BUCKET:-${APP}-docs-${ACCOUNT}}        # the v1 bucket; the template does not create it
HOST=${HOST_NAME:-pharmassist.aishwaryabhanage.com}
# LangSmith: on by default when .env has a key (the instances read the key itself from Secrets Manager);
# the project name comes from the environment, else .env, else "pharmassist"
env_value() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"; }
LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-$(env_value LANGSMITH_PROJECT)}; LANGSMITH_PROJECT=${LANGSMITH_PROJECT:-pharmassist}
if [ -z "${LANGSMITH_TRACING:-}" ]; then
  if [ -n "$(env_value LANGSMITH_API_KEY)" ]; then LANGSMITH_TRACING=true; else LANGSMITH_TRACING=false; fi
fi
echo "langsmith:    tracing=$LANGSMITH_TRACING project=$LANGSMITH_PROJECT"

case "$(stack_status)" in
  ROLLBACK_COMPLETE|ROLLBACK_FAILED|DELETE_FAILED)
    echo "stack $STACK is in $(stack_status): a first creation failed; run deploy/aws/v2/destroy.sh, then deploy again" >&2; exit 1 ;;
esac

# ---- certificate: HTTPS when one is ISSUED for the hostname, otherwise HTTP until it is ----
CERT=${CERTIFICATE_ARN:-}
if [ -z "$CERT" ] && [ -n "$HOST" ]; then
  CERT=$(aws acm list-certificates --region "$REGION" --certificate-statuses ISSUED \
    --query "CertificateSummaryList[?DomainName=='$HOST'].CertificateArn | [0]" --output text)
  [ "$CERT" = "None" ] && CERT=""
fi
if [ -n "$CERT" ]; then echo "certificate:  $CERT (HTTPS on 443, 80 redirects)"
else echo "certificate:  none ISSUED for $HOST yet; deploying HTTP-only (run request_cert.sh, then deploy again)"; fi

# ---- network: the default VPC and one default subnet per chosen AZ ----
VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
VPC_CIDR=$(aws ec2 describe-vpcs --region "$REGION" --vpc-ids "$VPC" --query 'Vpcs[0].CidrBlock' --output text)
AZS=${SUBNET_AZS:-${REGION}a,${REGION}b}
SUBNETS=$(aws ec2 describe-subnets --region "$REGION" --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
  Name=availability-zone,Values="$AZS" --query 'sort_by(Subnets,&AvailabilityZone)[].SubnetId' --output text | tr '\t' ',')
[ "$(echo "$SUBNETS" | tr ',' '\n' | grep -c .)" = 2 ] || { echo "expected 2 default subnets in $AZS, got: $SUBNETS" >&2; exit 1; }
echo "network:      $VPC ($VPC_CIDR) subnets $SUBNETS"

# ---- images ----
push() {  # repo, dockerfile -> prints the image URI by digest
  local repo=$1 file=$2
  aws ecr describe-repositories --repository-names "$repo" --region "$REGION" >/dev/null 2>&1 || {
    aws ecr create-repository --repository-name "$repo" --region "$REGION" --image-scanning-configuration scanOnPush=true \
      --tags Key=Project,Value="$APP" >/dev/null
    aws ecr put-lifecycle-policy --repository-name "$repo" --region "$REGION" --lifecycle-policy-text \
      '{"rules":[{"rulePriority":1,"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":5},"action":{"type":"expire"}}]}' >/dev/null
  }
  # Fargate and `docker pull` by digest need a single-platform Docker v2 manifest: no provenance index
  docker build --platform linux/arm64 --provenance=false -f "$file" -t "$REGISTRY/$repo:$TAG" . >&2 || return 1
  docker push "$REGISTRY/$repo:$TAG" >/dev/null || return 1
  echo "$REGISTRY/$repo@$(aws ecr describe-images --repository-name "$repo" --region "$REGION" \
    --image-ids imageTag="$TAG" --query 'imageDetails[0].imageDigest' --output text)"
}
param() {  # current value of a stack parameter (for SKIP_BUILD)
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Parameters[?ParameterKey=='$1'].ParameterValue" --output text
}
if [ "${SKIP_BUILD:-0}" = 1 ]; then
  APP_IMAGE=${APP_IMAGE:-$(param ApiImageUri)}; INGEST_IMAGE=${INGEST_IMAGE:-$(param IngestImageUri)}
  [ -n "$APP_IMAGE" ] && [ -n "$INGEST_IMAGE" ] || { echo "SKIP_BUILD needs an existing stack (or pass APP_IMAGE and INGEST_IMAGE)" >&2; exit 1; }
fi
# an image given in the environment is reused as is; the other one is built and pushed
if [ -z "${APP_IMAGE:-}" ] || [ -z "${INGEST_IMAGE:-}" ]; then
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
  # new repos (pharmassist-v2-*): the v1 Lambda still references images in pharmassist-web by digest
  # errexit doesn't reach inside $(...) in bash 3.2 (macOS), so each step's failure is checked here
  [ -n "${APP_IMAGE:-}" ] || APP_IMAGE=$(push "${APP}-v2-web" deploy/aws/Dockerfile) || { echo "API image build failed" >&2; exit 1; }
  [ -n "${INGEST_IMAGE:-}" ] || INGEST_IMAGE=$(push "${APP}-v2-ingest" deploy/aws/Dockerfile.ingest) || { echo "ingest image build failed" >&2; exit 1; }
else
  echo "reusing the images given in APP_IMAGE / INGEST_IMAGE (no build)"
fi
echo "api image:    $APP_IMAGE"
echo "ingest image: $INGEST_IMAGE"

# ---- stack (the template is > 51 KB, so it goes through the bucket) ----
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" --template-file deploy/aws/v2/template.yaml \
  --s3-bucket "$BUCKET" --s3-prefix cfn-templates \
  --role-arn "$EXEC_ROLE" --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset \
  --tags Project="$APP" \
  --parameter-overrides AppName="$APP" HostName="$HOST" CertificateArn="$CERT" \
    ApiImageUri="$APP_IMAGE" IngestImageUri="$INGEST_IMAGE" \
    VpcId="$VPC" VpcCidr="$VPC_CIDR" SubnetIds="$SUBNETS" BucketName="$BUCKET" \
    InstanceType="${INSTANCE_TYPE:-t4g.large}" DesiredCapacity="${DESIRED_CAPACITY:-2}" \
    DbInstanceClass="${DB_INSTANCE_CLASS:-db.t4g.small}" CacheNodeType="${CACHE_NODE_TYPE:-cache.t4g.small}" \
    CacheEngineVersion="${CACHE_ENGINE_VERSION:-8.2}" LangsmithTracing="$LANGSMITH_TRACING" \
    LangsmithProject="$LANGSMITH_PROJECT" \
    WorkerMinCount="${WORKER_MIN_COUNT:-1}"

# ---- schema ----
if [ "${SKIP_MIGRATE:-0}" = 1 ]; then echo "SKIP_MIGRATE=1: not running migrations"
else deploy/aws/v2/migrate.sh || { echo "migration failed; fix and rerun deploy/aws/v2/migrate.sh" >&2; exit 1; }; fi

# ---- summary ----
EIP1=$(out ElasticIp1); EIP2=$(out ElasticIp2)
ZONE=$(echo "$HOST" | awk -F. '{print $(NF-1)"."$NF}'); HOSTPART=${HOST%."$ZONE"}
cat <<EOF

deployed $TAG
Elastic IPs:   $EIP1  $EIP2
NLB:           $(out NlbDns)
URL:           $(out Url)
cluster:       $(out Cluster)   worker service: $(out WorkerService) (0 tasks until the queue has messages)
queue:         $(out QueueUrl)
database:      $(out DbEndpoint)   cache: $(out CacheEndpoint)

DNS at GoDaddy (My Products -> DNS for $ZONE), once, so https://$HOST reaches the stack:
  Type A   Name: $HOSTPART   Value: $EIP1   TTL 600
  Type A   Name: $HOSTPART   Value: $EIP2   TTL 600
(two A records for the same name: browsers use either address; the Elastic IPs stay fixed across deploys)
EOF
[ -n "$CERT" ] || echo "HTTPS is off until the certificate is ISSUED: deploy/aws/v2/request_cert.sh --wait, then rerun deploy.sh (SKIP_BUILD=1 is enough)."
