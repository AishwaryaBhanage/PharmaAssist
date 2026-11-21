# PharmAssist v2 on AWS

Always-on deployment of the v2 architecture (DESIGN.md, Architecture): static IPs, HTTPS on your hostname, two
API servers behind a load balancer with sticky sessions, PostgreSQL + pgvector, a Valkey semantic cache,
and a queue-fed ingestion worker that scales to zero. One CloudFormation stack, `pharmassist-v2`,
deployed with the `pharmassist-deployer` role; every resource is tagged `Project=pharmassist`.

```
 Browser ── https://pharmassist.aishwaryabhanage.com ── GoDaddy A records → two Elastic IPs
    │
 Network Load Balancer (TCP 443, 80 pass-through; one EIP per AZ; client IP preserved)
    │
 AWS WAF (300 req / 5 min per IP; AWS common rules in count mode)
    │
 Application Load Balancer (ACM certificate; 80 → 443; lb_cookie stickiness 1 day; health /health/ready)
    ├── EC2 app-a  t4g.large  ── Docker: API image (FastAPI + React build), logs → CloudWatch /ec2/pharmassist-api
    └── EC2 app-b  t4g.large     Auto Scaling group min 2 / max 4 (CPU 60 %), rolling replacement on deploy
           │           │               │                   └─ OpenAI (primary) / Anthropic (fallback) / LangSmith
           │           │               └─ ElastiCache for Valkey 8.2 (TLS, cache.t4g.small): semantic cache, limits, spend counters
           │           └─ RDS PostgreSQL 16 + pgvector (db.t4g.small, 20→100 GB gp3, 7-day backups, private)
           └─ S3 pharmassist-docs-<account> (the v1 bucket): sources, figure crops, uploads; presigned links
                  │
    admin upload ─┴─► SQS pharmassist-v2-ingest (+ DLQ after 3 attempts)
                           │ CloudWatch alarms on backlog (visible + in flight)
                           └─► ECS Fargate service pharmassist-v2-ingest: 0 tasks idle, 1 at ≥ 1 message,
                               2 at ≥ 10 (4 vCPU / 16 GB arm64; Docling, vision, chunking, embeddings → Postgres)
 one-off Fargate tasks with the API image: alembic migrations (migrate.sh), seed users (seed-users.sh)
 Secrets Manager: pharmassist/v2/jwt (generated), pharmassist/v2/app-keys (put_secrets.py), RDS master (managed)
```

Why this shape: an ALB cannot hold an Elastic IP, so an NLB with two EIPs fronts it; the ALB keeps the
cookie stickiness, WAF, HTTPS termination and HTTP routing the design calls for. The app servers and the
worker run in the default VPC's public subnets (no NAT gateway, ≈ $32/month saved); the database and the
cache are not publicly accessible and accept connections only from the app/worker/migration security groups.

## Files

| File | Purpose |
|---|---|
| `template.yaml` | the whole stack (parameters at the top; `cfn-lint` clean) |
| `deploy.sh` | build + push both images, deploy/update the stack, run migrations, print EIPs and DNS records |
| `request_cert.sh` | request the ACM certificate, print the GoDaddy CNAME, optionally wait until ISSUED |
| `put_secrets.py` | `.env` → Secrets Manager `pharmassist/v2/app-keys` (names printed, never values) |
| `migrate.sh` / `seed-users.sh` / `load-v1-data.sh` / `worker-run.sh` | one-off Fargate tasks: alembic, seed accounts, load the v1 corpus, run the worker by hand |
| `bootstrap.sh` | admin-only: apply `../bootstrap.yaml` and pre-create the service-linked roles |
| `destroy.sh` | delete the stack after typed confirmation; purge secret names; release stray EIPs |
| `common.sh` | shared helpers (`out`, `run_task`); sourced by the scripts |
| `../bootstrap.yaml` | the deploy identity (admin re-applies it for v2) |
| `../Dockerfile`, `../Dockerfile.ingest` | API image (node build stage + python:3.12-slim) and worker image |
| `../../docker-compose.yml` | the same services on a laptop: Postgres+pgvector, Valkey (search module), ElasticMQ, S3 |

## Prerequisites

1. **Bootstrap (account administrator, once).** The v2 stack needs permissions the v1 roles don't have
   (EC2, ELB, WAF, Auto Scaling, RDS, ElastiCache, SQS, Secrets Manager, ACM). Re-apply, as an admin,
   from the repository root:
   ```bash
   AWS_PROFILE=<admin> deploy/aws/v2/bootstrap.sh
   ```
   (`aws cloudformation deploy` of `bootstrap.yaml`, then the service-linked roles the stack's services need,
   created ahead of time so a first creation cannot race their IAM propagation.)
   The deployer keeps its `pharmassist*` scope; where a service has no resource names to scope on
   (EC2 create calls, Application Auto Scaling, ECS task definitions, ACM requests) the template says so.
2. **CLI profile** `pharmassist` assuming `pharmassist-deployer` (unchanged from v1):
   ```bash
   aws configure set profile.pharmassist.role_arn arn:aws:iam::<account>:role/pharmassist-deployer
   aws configure set profile.pharmassist.source_profile default
   aws configure set profile.pharmassist.region us-east-1
   ```
3. **Hostname and DNS.** `pharmassist.aishwaryabhanage.com`; the zone is at GoDaddy (not Route 53), so two
   records are added by hand: the ACM validation CNAME (step 1 below) and the A records (step 4).
4. Docker (arm64 builds via buildx/Desktop), Node is **not** needed locally (the image builds the frontend).
5. `.env` with `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY` (see `.env.example`).

## Deploy

All commands from the repository root with `AWS_PROFILE=pharmassist` (the scripts default to it).

```bash
# 1. certificate: prints the CNAME to add at GoDaddy, then waits for ISSUED (minutes once the record resolves)
deploy/aws/v2/request_cert.sh --wait
#    GoDaddy -> My Products -> DNS (aishwaryabhanage.com) -> Add: Type CNAME, Name _<token>.pharmassist, Value <token>.acm-validations.aws

# 2. stack: images -> ECR (pharmassist-v2-web, pharmassist-v2-ingest), CloudFormation, migrations. ~20 min first time.
deploy/aws/v2/deploy.sh
#    If the certificate is not ISSUED yet this deploys HTTP-only; rerun later with SKIP_BUILD=1 to switch on HTTPS.

# 3. secrets: .env -> pharmassist/v2/app-keys, then replace the instances so they read the keys at boot
.venv/bin/python deploy/aws/v2/put_secrets.py --refresh-instances

# 4. DNS: deploy.sh printed the two Elastic IPs. GoDaddy -> DNS -> Add two A records:
#    Type A, Name pharmassist, Value <EIP 1>, TTL 600   and   Type A, Name pharmassist, Value <EIP 2>, TTL 600

# 5. accounts: 1 admin + 3 staff; passwords are shown once in this terminal and the log stream is deleted
deploy/aws/v2/seed-users.sh

# 6. data: the v1 build (catalog + sources, sections, chunks with vectors, table rows, figure records) into
#    Postgres: packed into the documents bucket and loaded by scripts/migrate_v1_to_pg.py in a one-off task
deploy/aws/v2/load-v1-data.sh        # idempotent; --dry-run passes through
```

If a first stack creation fails (one failed resource rolls everything back), delete the stack and deploy
again reusing the pushed images: `APP_IMAGE=<uri@sha256> INGEST_IMAGE=<uri@sha256> deploy/aws/v2/deploy.sh`
(both URIs are in the previous run's output). A rollback can leave the two Elastic IPs behind
(`ROLLBACK_FAILED`): `aws cloudformation delete-stack --retain-resources Eip1 Eip2`, then release them.
The app-keys secret is created by the stack, so run `put_secrets.py` after the stack exists; a secret filled
before a failed creation is deleted with that stack.

Afterwards: `https://pharmassist.aishwaryabhanage.com` (login → ask → admin). `GET /health/ready` is the
load balancer's check; `aws logs tail /ec2/pharmassist-api --follow` shows the API, `/ecs/pharmassist-v2-ingest`
the worker. Instances have no SSH; use `aws ssm start-session --target <instance-id>` (Session Manager).

Redeploying code: `deploy/aws/v2/deploy.sh` again. New images change the launch template, and the Auto
Scaling group replaces instances one at a time (one always in service, each new one must pass
`/health/ready` before the next is replaced). Migrations run after the stack update; a migration that is
not backward compatible with the previous image should be deployed in two steps.

Order of operations inside the stack, for reference: the API container at boot fetches the RDS-managed
secret, the JWT secret and the app keys with the instance role and writes `/etc/pharmassist/api.env`
(mode 600). Nothing secret is in user-data, the launch template or the image. The worker and migration
tasks get the same values through ECS secret injection, and a small entrypoint composes `DATABASE_URL`
(URL-encoding the password) before `exec`-ing the command.

### Parameters you may change

`deploy.sh` reads these from the environment: `HOST_NAME`, `CERTIFICATE_ARN`, `SUBNET_AZS`
(default `us-east-1a,us-east-1b`), `INSTANCE_TYPE` (t4g.large), `DESIRED_CAPACITY` (2),
`DB_INSTANCE_CLASS` (db.t4g.small), `CACHE_NODE_TYPE` (cache.t4g.small), `CACHE_ENGINE_VERSION` (8.2),
`LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `SKIP_BUILD=1`, `SKIP_MIGRATE=1`. Template-only parameters:
`AllowedCidr` (who may reach the load balancers), `CacheAuthEnabled` (AUTH token in addition to TLS),
`DbEngineVersion`, `SsmParameterPrefix`.

## Cutover from v1

The v1 stack (`pharmassist`: Lambda + Function URL, DynamoDB, Pinecone) keeps running until v2 is verified.

1. Deploy v2 as above and migrate the data (`scripts/migrate_v1_to_pg.py` through `migrate.sh`'s task).
2. Verify on the v2 URL: login, a question, the same question again (cached), a forced fallback, an admin
   upload that ends up searchable; run the golden/visual evals against it.
3. Switch anything that still points at the Function URL to `https://pharmassist.aishwaryabhanage.com`.
4. Only then, and only after asking: `aws cloudformation delete-stack --stack-name pharmassist` (the
   bucket and DynamoDB table are `Retain`; the Pinecone index is deleted from the Pinecone console), and
   remove the `/pharmassist/prod/*` SSM parameters. The v1 ECR repos (`pharmassist-web`, `-ingest`) can go
   once the Lambda is gone; v2 uses `pharmassist-v2-*` so the two never share images.

## Cost (us-east-1, on-demand)

| Item | $/month |
|---|---|
| ALB | 17 |
| NLB | 17 |
| 2 Elastic IPs | 7 |
| WAF (web ACL + 2 rules + requests) | 6 |
| 2 × t4g.large | 98 |
| RDS db.t4g.small + 20 GB gp3 + backups | 28 |
| ElastiCache cache.t4g.small (custom parameter group, reserved-memory-percent 30) | 23 |
| SQS, S3, CloudWatch logs, Secrets Manager | 3 |
| **Always-on total** | **≈ 197** |
| Ingestion worker (Fargate 4 vCPU/16 GB arm64) | ≈ 0.20 per document, 0 when idle |

Plus model spend per question (bounded by the daily cap in `config.yaml`). Scaling to 4 instances under
load adds ≈ $49 per extra t4g.large. A cheaper variant (t4g.medium, db.t4g.micro, no NLB)
is ≈ $100.

## Teardown

```bash
deploy/aws/v2/destroy.sh     # asks you to type the stack name
```
Deletes the stack (load balancers, EIPs, instances, RDS — a final snapshot is kept —, ElastiCache, queues,
ECS cluster and service, roles, alarms, secrets) and purges the secret names so a redeploy can reuse them.
Kept on purpose: the S3 bucket (documents), the ECR repositories, the RDS final snapshot (delete it in the
console when the data is no longer needed), the v1 stack, the ACM certificate (free).

## Local development (`deploy/docker-compose.yml`)

```bash
docker compose -f deploy/docker-compose.yml up -d                       # postgres, valkey, elasticmq, s3 (+ bucket init)
docker compose -f deploy/docker-compose.yml --env-file .env --profile app up --build   # + api on :8000, migrate, worker
docker compose -f deploy/docker-compose.yml down -v                     # stop and wipe the volumes
```
Host-side values for running the API from `.venv` are listed in the compose file header and in
`.env.example`. The S3 service is RustFS (MinIO's public images were withdrawn in 2025; RustFS speaks the
same API and accepts the `MINIO_ROOT_*` variables), console at http://localhost:9001. Valkey runs
`valkey-bundle` 8.1 for the search module (`FT.CREATE`/`FT.SEARCH`); ElastiCache's 8.2 has it built in.

## Notes and known limits

- **Stickiness** is at the ALB target group (`lb_cookie`, 86400 s). The NLB in front is TCP pass-through,
  so the cookie still reaches the ALB and the client IP is preserved for WAF and rate limits.
- **HTTP-only mode** (no certificate yet): the NLB and ALB listen on 80 only; the browser gets `http://<EIP>`.
  Cookies are then sent without `Secure`; switch to HTTPS before real use.
- **Worker scale-in**: the step policy sets exact capacity from the backlog (visible + in-flight messages),
  so a task finishing the last message is not killed early; with 10+ messages a second task starts and
  stops again when the backlog drops under 10 (Fargate gives it 120 s to finish its stage; the message
  returns to the queue if it does not). A stack update that changes the service resets desired count to 0.
- **ElastiCache Valkey vector search** (stream D's findings): Valkey 8.2, node-based, cluster mode off,
  single node. Burstable nodes need a custom parameter group with `reserved-memory-percent` 50 (micro) /
  30 (small); the template creates and attaches it. cache.t4g.small is the floor: micro leaves ~0.25 GB
  for ~400 MB of 3072-d entries. TLS is always on; the client uses `rediss://` with 1 s timeouts
  (`REDIS_URL` is composed that way).
- **Seed passwords in logs**: a Fargate task can only print to CloudWatch; `seed-users.sh` deletes that
  log stream after showing it. Prefer running `scripts/seed_users.py` from a laptop against the database
  through an SSM port-forward if you'd rather they never touch CloudWatch.
- **Rollback of a first deploy**: if the first `deploy.sh` fails, the stack is `ROLLBACK_COMPLETE` and
  must be removed with `destroy.sh` before trying again (deploy.sh says so).
