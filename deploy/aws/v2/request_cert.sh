#!/usr/bin/env bash
# Request (or find) the ACM certificate for the public hostname and print the DNS validation record to
# add at the registrar (GoDaddy for aishwaryabhanage.com; nothing is in Route 53). Run from
# the repository root:
#   deploy/aws/v2/request_cert.sh                                   # pharmassist.aishwaryabhanage.com
#   deploy/aws/v2/request_cert.sh pharmassist.aishwaryabhanage.com --wait   # also poll until ISSUED
# The certificate must be ISSUED before deploy.sh can enable HTTPS; until then the stack serves HTTP.
set -euo pipefail
. "$(dirname "$0")/common.sh"

HOST=${1:-${HOST_NAME:-pharmassist.aishwaryabhanage.com}}
WAIT=0
[ "${2:-}" = "--wait" ] && WAIT=1
# the registrar wants the record name relative to the zone; the zone is the last two labels unless given
ZONE=${DNS_ZONE:-$(echo "$HOST" | awk -F. '{print $(NF-1)"."$NF}')}

ARN=$(aws acm list-certificates --region "$REGION" --certificate-statuses PENDING_VALIDATION ISSUED \
  --query "CertificateSummaryList[?DomainName=='$HOST'].CertificateArn | [0]" --output text)
if [ -z "$ARN" ] || [ "$ARN" = "None" ]; then
  ARN=$(aws acm request-certificate --region "$REGION" --domain-name "$HOST" --validation-method DNS \
    --key-algorithm RSA_2048 --tags Key=Project,Value="$APP" --query CertificateArn --output text)
  echo "requested $ARN"
else
  echo "existing certificate $ARN"
fi

# the validation record appears a few seconds after the request
for i in $(seq 1 12); do
  REC=$(aws acm describe-certificate --region "$REGION" --certificate-arn "$ARN" \
    --query 'Certificate.DomainValidationOptions[0].ResourceRecord.[Name,Value]' --output text)
  [ -n "$REC" ] && [ "$REC" != "None" ] && [ "$REC" != "None	None" ] && break
  sleep 5
done
NAME=$(echo "$REC" | cut -f1); VALUE=$(echo "$REC" | cut -f2)
[ -n "$NAME" ] && [ "$NAME" != "None" ] || { echo "ACM has not produced the validation record yet; rerun in a minute" >&2; exit 1; }
REL=${NAME%.}; REL=${REL%."$ZONE"}       # _abc123.pharmassist  (GoDaddy appends the zone itself)

STATUS=$(aws acm describe-certificate --region "$REGION" --certificate-arn "$ARN" --query 'Certificate.Status' --output text)
cat <<EOF

Certificate: $ARN   (status: $STATUS)

Add this DNS record at GoDaddy (My Products -> DNS for $ZONE -> Add record):
  Type:   CNAME
  Name:   $REL
  Value:  ${VALUE%.}
  TTL:    600 (any value works)
ACM checks the record every few minutes and issues the certificate once it resolves (usually < 30 min).
Then: export CERTIFICATE_ARN=$ARN  (deploy.sh also finds an ISSUED certificate for $HOST on its own)
EOF

if [ "$WAIT" = 1 ]; then
  echo "waiting for ISSUED (up to 60 min; Ctrl-C is safe, the request keeps going) ..."
  for i in $(seq 1 120); do
    STATUS=$(aws acm describe-certificate --region "$REGION" --certificate-arn "$ARN" --query 'Certificate.Status' --output text)
    case "$STATUS" in
      ISSUED) echo "ISSUED: $ARN"; exit 0 ;;
      FAILED|VALIDATION_TIMED_OUT|REVOKED) echo "certificate $STATUS" >&2; exit 1 ;;
    esac
    sleep 30
  done
  echo "still $STATUS after 60 min; check the CNAME at GoDaddy and rerun with --wait" >&2
  exit 1
fi
