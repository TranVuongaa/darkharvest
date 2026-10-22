# Darkharvest

Export OptiSigns support articles as clean Markdown and synchronize them with an
existing OpenAI vector store for a support assistant.

**Setup** — Python 3.11+ on macOS or Linux. From the repository root:

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # Only if you do not already have a .env file.
```

For uploads, set `OPENAI_API_KEY` and `OPENAI_VECTOR_STORE_ID` in `.env`.
Set `ARTICLES_DIR` in `.env` to the directory used for exports and uploads
(default: `articles`):

```dotenv
ARTICLES_DIR="articles"
LIMIT=
```

Leave `LIMIT` blank to process all articles. Run commands from the repository
root; relative paths resolve against the current working directory. Add any
custom generated directory inside the repository to `.gitignore`.

**Run locally**

```sh
LIMIT= python main.py                       # Export all articles, then upload.
python -m unittest discover -s tests -v     # Run tests.
```

`--limit` counts API records, so skipped or failed records can reduce the output
count. Uploads process all Markdown files in `ARTICLES_DIR`.

## Delta synchronization

Each run exports articles again, then calculates SHA-256 over the exact bytes of
each Markdown file (including front matter and whitespace). The uploader lists
all vector-store file attachments, following SDK pagination, and compares this
local digest with remote `attributes.sha256`; it does not download remote content
or use a local hash cache. SHA-256 is the comparison value; `attributes` is where
that value and the article identity are stored:

```json
{
  "manager": "optibot-articles-v1",
  "article_key": "123456789",
  "sha256": "<SHA-256 hex digest of the Markdown bytes>"
}
```

`article_key` is the Zendesk ID at the end of the filename, falling back to the
filename when no ID is present. Only attachments with this `manager` are managed.

| Remote state for the article key | Result |
| --- | --- |
| No managed attachment | Upload and index; count as `added`. |
| A `completed` attachment has the same SHA-256 | Skip upload/indexing; count as `skipped`. |
| Managed attachments exist, but none is completed with the same SHA-256 | Upload and index a replacement; count as `updated`. |

Old managed attachments for that key are detached only after the current version
is indexed successfully. A retry also removes obsolete attachments when the
matching version already exists. Detaching an old attachment does not delete its
underlying OpenAI File. Indexing or cleanup failures are logged per article and
make the upload job exit nonzero; an indexing failure leaves the old attachment
in place. Duplicate article IDs in the local input abort synchronization before
uploads, so remove stale renamed Markdown copies before reusing an export folder.

Metadata-only changes in front matter also change the hash. Deleted source
articles are not pruned. The upload lock coordinates processes sharing a local
article directory; separate ECS tasks must not overlap.

## Schedule

The container runs `python main.py` once and exits. There is no scheduler in the
application or schedule definition checked into this repository. The deployed
schedule and its timezone have not been verified.

For a daily deployment, configure an **EventBridge Scheduler** schedule targeting
ECS `RunTask` on cluster `optibot`, with the Fargate task definition and networking
below. For example, `cron(0 2 * * ? *)` with timezone `Asia/Ho_Chi_Minh` runs at
02:00 Vietnam time daily; this is a suggested configuration, not a claim about
the existing deployment. Disable the flexible time window if exact timing is
required. Use a Scheduler execution role that can run the task and pass its ECS
roles. Keep runs from overlapping, including manual runs and retries.

Verify the actual configuration before changing it:

```sh
aws scheduler list-schedules --region ap-southeast-2
aws scheduler get-schedule --region ap-southeast-2 \
  --group-name '<schedule-group>' --name '<schedule-name>'
# If the deployment uses a legacy EventBridge scheduled rule instead:
aws events list-rules --region ap-southeast-2
```

Check the expression, timezone, enabled state, target task revision, and network
configuration. For a full export, leave `LIMIT` blank and omit `--limit`.

## Deploy to ECS Fargate

Prerequisites: Docker, an authenticated AWS CLI, an ECR repository `optibot`, ECS
cluster `optibot`, and a registered Fargate task definition `optibot` in
`ap-southeast-2`. These AWS resources are not provisioned by this repository.
The commands below follow the existing deployment notes in `build.txt`.

The task definition must use the ECR image, Linux x86_64 (matching the build),
`awsvpc` networking, suitable CPU/memory, and an execution role able to pull from
ECR and write CloudWatch logs. Set `OPENAI_VECTOR_STORE_ID`, `ARTICLES_DIR=/app/articles`
and `LIMIT=""`; inject `OPENAI_API_KEY` through ECS secrets backed by Secrets Manager
or SSM Parameter Store with the corresponding execution-role permissions. The
Docker build excludes `.env`. Configure `awslogs` with group `/ecs/optibot`, region
`ap-southeast-2`, and a stream prefix such as `ecs`.

From the repository root, build and push:

```sh
export AWS_REGION=ap-southeast-2
export AWS_DEFAULT_REGION="$AWS_REGION"
export ACCT="$(aws sts get-caller-identity --query Account --output text)"
export ECR="$ACCT.dkr.ecr.$AWS_REGION.amazonaws.com"
aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR"
docker build --platform linux/amd64 -t "$ECR/optibot:latest" .
docker push "$ECR/optibot:latest"
```

The existing notes use `latest`; ensure the task definition references that image.
For reproducible releases, use a unique image tag, register a task-definition
revision referencing it, and update the schedule target to that revision. Pushing
an image does not launch a job or update an already running task.

Launch a verification run using a public subnet with an internet gateway and a
security group allowing outbound HTTPS (or adapt to private subnets with NAT):

```sh
export SUBNET='<public-subnet-id>'
export SG='<security-group-id>'
aws ecs run-task --cluster optibot --launch-type FARGATE \
  --task-definition optibot \
  --network-configuration "awsvpcConfiguration={subnets=[$SUBNET],securityGroups=[$SG],assignPublicIp=ENABLED}"
aws logs tail /ecs/optibot --follow
```

Check `run-task` for failures, then inspect the returned task ARN with
`aws ecs describe-tasks --cluster optibot --tasks '<task-arn>'`. Success requires
the container to exit with code 0 and the log's `Run summary` to report
`status: success`. A scrape failure skips uploading. Container-local exports and
log files are ephemeral; CloudWatch retains the stdout/stderr logs according to
the log group's retention policy.

## Job logs

[CloudWatch: /ecs/optibot (ap-southeast-2)](https://226147734550-lti7bpki.ap-southeast-2.console.aws.amazon.com/cloudwatch/home?region=ap-southeast-2#logsV2:log-groups/log-group/$252Fecs$252Foptibot)
requires access to the AWS account. Local runs write `logs/scraper.log`,
`logs/ingestion.log`, and `logs/last-run.json`; the pipeline also prints its run
summary to stdout for CloudWatch collection.

To capture an existing CloudWatch run, select its stream in the console or list
streams with `aws logs describe-log-streams --log-group-name /ecs/optibot`, then:

```sh
aws logs get-log-events --log-group-name /ecs/optibot \
  --log-stream-name '<stream-for-the-run>' --start-from-head \
  --query 'events[].message' --output text > run.log
```

Check that the export includes the complete run, including its final summary;
large streams may require additional requests using the returned forward token.
Review the log for credentials or sensitive content before committing. To archive
an existing `run.log` using the Vietnam calendar date:

```sh
mkdir -p docs
cp run.log "docs/run-log-$(TZ=Asia/Ho_Chi_Minh date +%F).txt"
git add docs
git commit -m "Add job run log"
git push
```

**Design and limitations** — Uses the public Zendesk API, preserves headings,
fenced code and relative links, and removes page clutter. Hashes detect unchanged
content. Images are not downloaded, and removed source articles are not pruned.

**Sample assistant answer** — “How do I add a YouTube video?”

<a href="images/assistant_answer.png"><img src="images/assistant_answer.png" alt="OptiBot answering how to add a YouTube video in OptiSigns, with a source citation" height="280"></a>
