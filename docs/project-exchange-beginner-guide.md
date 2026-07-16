# Beginner Guide: Connecting Project Playbook To Project Exchange

## Read This First

Do not merge or copy files yet. This guide explains the sequence we will follow
together after the current runner changes are reviewed, committed, and pushed.

The integration has three core pieces:

1. `project-exchange`: the website and cloud control plane. It owns accounts,
   profiles, documents, job targets, permissions, and run history.
2. `project-playbook`: this repository. It owns the deterministic runner and
   trusted playbooks.
3. An executor: something authorized to run the selected playbook. The desktop
   companion is the reliability baseline. We will also prototype a cloud
   executor for zero-install use and run a smaller Chrome/Edge extension test.

React never imports Python directly. Django, the companion, and the cloud
worker can install the `project-playbook-runner` Python package. An extension
would implement the same contract in browser-compatible code.

```text
Applicant uses Project Exchange website
                 |
                 v
        Django creates a run
                 |
                 v
Authorized executor claims that user's run
                 |
                 v
Project Playbook fills a local or cloud browser
                 |
                 v
Applicant handles required checkpoints,
reviews, and clicks final submit
```

A normal Project Exchange webpage cannot control a university website in
another browser tab. Zero-install use is still possible by running the browser
in an isolated cloud worker and securely streaming it to the applicant. The
extension experiment is a smaller install than a companion, but it has browser
permission, store-policy, upload, and multi-domain constraints that must be
proven before it becomes a supported executor.

## Confirmed Direction

This guide uses these confirmed starting assumptions:

1. Keep one executor-neutral run/playbook contract. Build a macOS developer
   companion first, support Windows before a public desktop pilot, prototype a
   cloud worker, and test Chrome/Edge without committing to two production
   engines.
2. Put the first Auto Apply interface in the existing Django applicant
   workspace. React currently powers the recipe wizard, not the main workspace.
3. Treat the current deployment as test-only. The Tailscale and Cloudflare
   addresses currently provide HTTPS, but the raw EC2 origin remains available
   over plain HTTP and production still needs one permanent HTTPS domain.
4. Show Auto Apply only for listed positions with a reviewed, versioned
   playbook release. New targets may arrive daily or weekly during the hiring
   season.
5. Once onboarding is complete, one click starts account creation and form
   filling. CAPTCHA, legally meaningful attestations, and final submission may
   still require the applicant.
6. Normal email verification is automatic. For the first pilot, the applicant
   creates and retains access to a dedicated Gmail account, grants Project
   Exchange access, and uses that exact address for university/ATS accounts.
   The private prototype uses a Gmail app password; public onboarding uses a
   `Connect Gmail` OAuth flow. Manual code/link entry is recovery-only.

Changing one of these choices will not invalidate the architecture, but it will
change the first implementation tasks.

## Current Local Checkpoint

Phases 1 through 4 and the first validation-only integration slice are complete
on the current Mac:

- both repositories are cloned beside each other;
- Project Exchange is on `feature/auto-apply-foundation`;
- Python 3.12, Docker Desktop, PostgreSQL, and Redis work;
- migrations and Django system checks pass;
- all 258 Project Exchange tests and all 87 runner tests pass;
- the Django applicant workspace and React/Vite wizard both load locally;
- fake test accounts were seeded;
- Project Exchange's virtual environment imports the runner from this checkout
  and validates the maintained playbook matrix;
- the runner accepts owner-scoped dictionaries without temporary JSON files;
- Django has an `autoapply` app, target hash/final-gate checks, Gmail connection
  metadata, private profile forms, and owner/target-scoped answer sets;
- the runner owns the canonical intake choices, per-playbook requirements,
  required documents, position questions, and known release blockers;
- `/workspace/?autoapply_target=<id>#autoapply-profile` renders the reusable
  private profile and highlights fields required by the selected position;
- `/auto-apply/positions/<id>/answers/` stores only that position's additional
  referral, institution relationships, and genuinely unique questions;
- `GET /api/auto-apply/positions/<id>/readiness/` reports safe preflight state;
- all ten maintained playbooks are synced as active local website listings; and
- posting lists, timelines, applicant match cards, and position pages render
  Auto Apply actions/readiness without enabling browser execution.

The next code phase is encrypted Gmail secret handling and the authenticated run
queue/worker contract. The setup commands below remain as a reproducible record
for another machine.

## Phase 0: Coordinate Before Touching Code

Coordinate these repository decisions with your coworker:

- the branch you should start from;
- whether Auto Apply should first appear in the Django workspace or a new React
  page;
- who reviews database migrations and API changes; and
- who owns the permanent production domain/TLS configuration.

Never develop directly on `main`. We will use a feature branch and a pull
request so your coworker can review the integration.

The current runner repository also has a large, intentional cleanup in the
working tree. Review and commit that work before Project Exchange pins a runner
version. A production dependency must point at a real commit, not uncommitted
files on one laptop.

## Phase 1: Arrange The Repositories

Keep the repositories next to each other, not inside each other:

```text
/Users/kateli/
  playbook/
  project-exchange/
```

Clone the private repository:

```bash
cd /Users/kateli
git clone https://github.com/SharpDressedMan/project-exchange.git
cd project-exchange
git status
git switch -c feature/auto-apply-foundation
```

Expected result:

- `git status` says the checkout is clean;
- the branch name is `feature/auto-apply-foundation`; and
- `/Users/kateli/playbook` and `/Users/kateli/project-exchange` both exist.

If cloning says `Repository not found`, stop. That means the GitHub account or
credential in this terminal does not have access to the private repository.

## Phase 2: Install Mac Prerequisites (Complete Here)

The current machine now has Homebrew, Git, Node, npm, Docker Desktop, and Python
3.12. On another Mac, install missing prerequisites as follows.

Install them:

```bash
brew install python@3.12
brew install --cask docker-desktop
open -a Docker
```

Docker Desktop may ask for macOS permissions. Wait until it says the engine is
running, then open a new terminal and verify:

```bash
/opt/homebrew/bin/python3.12 --version
docker --version
docker compose version
node --version
npm --version
```

Expected result:

- Python reports `3.12.x`;
- Docker and Docker Compose report versions without connection errors; and
- Node/npm report versions.

Do not continue while `docker info` says it cannot connect to the daemon.

## Phase 3: Run Project Exchange Unchanged (Complete Here)

First prove the coworker's project works by itself. This separates existing
setup problems from integration problems.

Create the environment and Python virtual environment:

```bash
cd /Users/kateli/project-exchange
cp .env.example .env
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Leave `OPENAI_API_KEY` blank for this setup. Project Exchange has its own
optional AI-powered market/avatar features, but they are unrelated to the
sunset runtime recovery in Project Playbook and are not needed here.

Start PostgreSQL and Redis:

```bash
docker compose up -d db redis
docker compose ps
```

Expected result: both `db` and `redis` become healthy.

Create the database tables and start Django:

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput
python manage.py test
python manage.py runserver
```

The current checkout reports 233 passing tests. `collectstatic` is needed before
the baseline test command because production-style static-file storage expects
its generated manifest.

Keep that terminal open. Django should be available at
`http://localhost:8000`.

Open a second terminal for React:

```bash
cd /Users/kateli/project-exchange/frontend
npm ci
cp .env.example .env
npm run dev
```

The Vite wizard should be available at `http://localhost:5173`.

Optional local test accounts can be created in a third terminal:

```bash
cd /Users/kateli/project-exchange
source .venv/bin/activate
python manage.py seed_testdata --seed 7
```

The repository's seeder creates local applicants such as `a1` with password
`1`. Those credentials are only for local development.

Checkpoint before integration:

- `http://localhost:8000` loads;
- an applicant can sign in and open the Application workspace;
- `http://localhost:5173` loads the recipe wizard; and
- Django, PostgreSQL, Redis, and React show no startup errors.

Stop a foreground server with `Ctrl-C`. Stop the data containers without
deleting their data with:

```bash
docker compose down
```

Never add `-v` unless you intentionally want to erase the local database.

## Phase 4: Link The Runner For Local Development (Complete Here)

The two repositories stay separate. Install this repository into Project
Exchange's virtual environment as an editable package:

```bash
cd /Users/kateli/project-exchange
source .venv/bin/activate
python -m pip install -e /Users/kateli/playbook
python -m pip check
python -c "import playbook_runner; print(playbook_runner.__file__)"
```

Expected result: the printed path starts with `/Users/kateli/playbook/`.

The committed fake profiles contain document paths relative to the Playbook
repository. Run fixture-based CLI validation from `/Users/kateli/playbook`.
The future Django/companion adapter will supply absolute paths to private,
per-run document copies instead.

This is development-only configuration. Do not commit an absolute
`/Users/kateli/...` path to Project Exchange. Production and companion builds
will install a reviewed runner commit or wheel.

The validation adapter uses `PLAYBOOK_CATALOG_DIR`. Its local default already
resolves sibling repositories, or it can be set explicitly in Project
Exchange's untracked `.env`:

```text
PLAYBOOK_CATALOG_DIR=/Users/kateli/playbook/playbooks
```

That path lets local Django validation find the maintained YAML catalog. In a
release, the backend and companion use a versioned catalog/manifest instead of
a developer's filesystem path.

The website now calls only the runner's browser-free inspection and validation
API. Django still does not launch a live Playwright browser.

## Phase 5: Add A Dedicated Django App

The foundation created a dedicated Django app in Project Exchange:

```bash
cd /Users/kateli/project-exchange
source .venv/bin/activate
python manage.py startapp autoapply
```

The intended Project Exchange organization is:

```text
project-exchange/
  autoapply/
    migrations/
    services/
      catalog.py
      profile_adapter.py
      readiness.py
    templates/autoapply/
    admin.py
    apps.py
    forms.py
    models.py
    urls.py
    views.py
    tests.py
  companion/
    # local reliability-baseline client and packaging
  cloud_runner/
    # later prototype: isolated Playwright worker/live browser
  extension/
    # bounded Chrome/Edge feasibility experiment
  frontend/
    # existing React recipe wizard
  wizard/templates/wizard/position.html
    # first Auto Apply readiness interface
```

`autoapply` is in `INSTALLED_APPS`; its first owner-scoped endpoint is under
`/api/auto-apply/`.

Do not put auto-apply records into these existing models:

- `wizard.Submission` is a generic/public recipe submission;
- `candidate.CandidateProfile` is an employer-facing extracted profile; and
- `accounts.Profile` stores the user's role and public/profile settings.

Auto-apply needs a private data boundary. The migrations now add
`ApplicationProfile`, `ApplicationTarget`, `ApplicationMailbox`, and
`ApplicationAnswerSet`. Add the remaining runtime models in later reviewed migrations:

- `ApplicationProfile` (implemented): private runner-shaped supplemental data
  and schema version;
- `ApplicationAnswerSet` (implemented): one private owner-and-target scoped map
  for the questions unique to a listed position;
- `AutomationDevice`: paired companion, version, credential/public key, status,
  and last heartbeat;
- `ApplicationTarget` (implemented): maintainer-approved listed position,
  external URL, allowed domains, trusted playbook id/version/hash, and last
  verification state;
- `ExternalApplicationAccount`: per-user account scope and encrypted credential
  reference so later positions reuse an account instead of registering again;
- `ApplicationMailbox` (metadata implemented): exact applicant-owned Gmail
  address, connection method/status, and encrypted secret reference; never a
  plaintext mailbox password, app password, or OAuth token;
- `EmailVerificationExpectation`: one active run's expected recipient/sender,
  allowed link pattern, expiry, and one-use match state without retaining the
  extracted secret;
- `ApplicationRun`: user selection/overrides, immutable snapshot hashes,
  executor mode, claimed device/worker, lease, and current step;
- `ApplicationEvent`: ordered, sanitized progress events;
- `HumanCheckpoint`: typed CAPTCHA, attestation, unexpected-prompt, or final
  review pause with expiry/resume state; and
- `ApplicationArtifact`: owner-scoped failure evidence with retention metadata.

Every applicant-private record must have an owner, and every private endpoint
must filter by `request.user`. Global supported-target records are
maintainer-controlled and read-only to applicants. Knowing a numeric run id
must never grant access.

After model changes, the normal commands are:

```bash
python manage.py makemigrations autoapply
python manage.py migrate
python manage.py test autoapply
```

Your coworker should review the generated migration before it is committed.

## Phase 6: Build The Private Profile Adapter

Project Exchange and Project Playbook use different public profile shapes. Do
not pass the public `CandidateProfile` directly to the runner.

`autoapply/services/profile_adapter.py` will map private Project Exchange data
into the runner contract, for example:

```text
full_name.first       -> person_name.legal_name.first
full_name.last        -> person_name.legal_name.last
contact_email         -> emails.preferred_contact_email
education[]           -> education.schools[]
uploaded CV           -> documents.resume_path_or_url
```

The private workspace intake now includes full address, phone, employment,
education, references, voluntary demographics, application defaults, and every
document kind referenced by maintained playbooks. Canonical options come from
the runner's equivalence-aware intake contract. Position-specific values are
collected on that position and stored separately from reusable profile facts.

Add application-email onboarding as private configuration. The user creates a
dedicated Gmail account for applications, keeps access to it, and authorizes
Project Exchange to read it. That exact address is used by university accounts;
there is no Project Exchange alias or forwarding layer. For the private
prototype, use a revocable Gmail app password over the runner's existing IMAP
path and never ask for the normal Google password. Before a public pilot, build
a `Connect Gmail` OAuth flow, request only the necessary read capability, and
complete Google's restricted-scope approval and security requirements.

A central mailbox broker automatically polls for an active run's expected
message, extracts an allowlisted link/code in memory, and passes only that value
to the executor. Ordinary messages stay in the mailbox for the user to monitor.
The broker should not send, delete, or alter mail. Manual link/code entry is
recovery-only. Store every mailbox credential or token in encrypted secret
storage and make it available only to this broker for a short polling operation.

External ATS accounts are tracked by scope: create once, then reuse for later
jobs on that ATS/university tenant. Generate a different strong password for
each external account and store it through encrypted secret storage.

The runner now exposes `build_context`, `inspect_playbook`, and
`validate_application` for in-memory integration. Django does not write a
permanent applicant JSON file to validate a request.

## Phase 7: Add Validation Before Browser Execution

The first working integration should validate only. It should not launch a
browser.

Suggested flow:

1. Applicant selects a supported job and documents.
2. Django verifies ownership and builds the private runner profile.
3. Django loads the trusted playbook by id and pinned version.
4. The adapter calls the runner parser/context/dry-run APIs.
5. The API returns `ready: true` or applicant-friendly missing-field errors.
6. Only a ready target can become an `ApplicationRun`.

Readiness also checks that the target's complete first-time account path,
mailbox-verification requirements, uploads, human checkpoints, and final gate
were verified. A YAML file containing TODO or returning-user-only steps is not
enough to enable Auto Apply.

The implemented first endpoint is:

```text
GET /api/auto-apply/positions/<id>/readiness/
```

Run creation, events, cancellation, and checkpoint endpoints come only after
the run/lease models and executor authentication are implemented.

These are authenticated endpoints. Do not copy the current `csrf_exempt`
submission endpoint. Require login and CSRF protection for browser requests.

## Phase 8: Add The First User Interface

The first interface is an Auto Apply panel on each position detail page. Public
visitors get a sign-in action; applicants get owner-scoped readiness; employers
see an applicant-only state. This puts support status beside the exact job and
leaves the existing React recipe wizard untouched. Add the queue and
cross-position workflow to the applicant workspace when `ApplicationRun`
exists.

The applicant's reusable private fields are edited in the workspace at
`/workspace/#autoapply-profile`. A position links to
`/auto-apply/positions/<id>/answers/` for questions that belong only to that
application. Choice controls on both pages come from the runner's canonical
intake/equivalence vocabulary rather than free-form website constants.

The current foundation also adds Auto Apply actions to the postings list,
timeline detail panel, and applicant match cards. Rebuild the local supported
catalog at any time with:

```bash
python manage.py sync_playbook_catalog --activate
```

The future workspace queue should show:

- which execution modes are available and whether a selected companion is
  connected/current;
- the selected position and supported playbook;
- whether the dedicated application mailbox is connected;
- profile/document readiness;
- missing information that the applicant must fix;
- an Auto Apply button only when validation succeeds;
- queued positions, one active run, progress, and human checkpoints;
- Cancel/Resume controls; and
- `review_ready` with the local or streamed browser when the executor reaches
  `pause_for_user`.

This is the fastest path because the workspace is already authenticated and
owner-scoped. It also avoids solving cross-origin session/CSRF behavior at the
same time as the runner integration.

If the interface must be React, build a dedicated auto-apply page rather than
mixing it into the recipe FSM. React requests must send the session cookie and
CSRF token, Django must allow credentialed development CORS, and production
should remain single-origin.

## Phase 9: Build Executors In Evidence-Driven Order

These components do not exist yet. Build them against one shared run snapshot,
event, and checkpoint contract so the website does not care where the browser
runs.

### Reliability Baseline: Local Companion

Build the first companion as a developer-only macOS command-line program before
packaging a desktop app. It will:

1. pair with a Project Exchange account using a short-lived code;
2. store a revocable device credential in the macOS Keychain;
3. poll Django over HTTPS for that user's run;
4. claim one run with a lease and idempotency key;
5. download a signed, trusted playbook plus short-lived document references;
6. resolve/create the scoped external account and invoke the installed Project
   Playbook package;
7. launch a visible, isolated Playwright browser;
8. post sanitized events and heartbeats;
9. map typed checkpoints to a local notification/UI gate;
10. wait while the applicant completes CAPTCHA/review and clicks final submit;
    and
11. clean up temporary data after completion or cancellation.

The Django validation service does not install a browser binary. The companion
environment does, using the runner's pinned Playwright version:

```bash
python -m playwright install chromium
```

The companion must never accept raw Python, JavaScript, YAML, selectors, file
paths, or URLs supplied directly by an end user. It receives a trusted run
manifest created by the backend and verifies the playbook version/hash and
allowed domain.

After the command-line prototype is reliable, package and sign it as a macOS
application with an updater. Add Windows before a public desktop pilot; Linux
can follow measured demand.

### Zero-Install Prototype: Cloud Worker

Run the same pinned Python runner in a non-root, sandboxed, short-lived browser
container. Give it only one run's short-lived data grants. Add an authenticated
live-browser view for CAPTCHA, attestations, and final review. Enforce worker,
per-domain, and unattended-checkpoint limits.

This prototype must measure browser minutes, memory, peak queue depth, CAPTCHA
frequency, university blocks of cloud IP addresses, and reconnect behavior. A
few hundred playbooks can still produce many thousands of user runs.

### Smaller Experiment: Chrome/Edge Extension

Implement only enough of the shared action contract to test three playbooks: a
simple form, an upload-heavy form, and a popup/multi-domain flow. Investigate
Chrome's `userScripts` permission and store policy before relying on remotely
updated playbooks. Users must install the extension and may need to enable an
additional Allow User Scripts toggle, so it is not a zero-install mode.

Do not maintain two complete production engines unless the experiment proves
the extension reliable and publishable.

## Phase 10: Prepare Production Safely

Do not test real applicant data or device pairing over plain HTTP. Before public
testing:

1. Put HTTPS in front of Project Exchange and enable secure cookies.
2. Fix authenticated SPA CSRF/session behavior.
3. Move private documents from a single EC2 Docker volume to owner-scoped
   private object storage with short-lived download grants.
4. Add encrypted external-account and mailbox secret storage, a secured central
   mailbox polling broker, provider connection/revocation health checks, and
   automatic verification with recovery behavior and minimal message retention.
5. Add device revocation, cloud-worker identities, run leases, idempotent
   claims, typed checkpoint expiry, and audit events.
6. Sign companion installers, updates, and playbook manifests.
7. Add retention/deletion controls for profile snapshots and artifacts.
8. Add one-active-run queueing, duplicate prevention, and per-user/per-site
   rate limits.
9. Security-review the complete path before inviting outside users.

The production dependency must be immutable. Use a reviewed wheel, private
package registry, or exact Git commit. Never deploy from an editable checkout or
an unpinned branch.

## Recommended Pull Request Sequence

Keep changes small enough for your coworker to review:

1. **Runner contract PR** in `playbook`: dictionary-based context API and tests.
2. **Backend foundation PR** in `project-exchange`: `autoapply` models,
   ownership tests, admin, and migrations.
3. **Validation PR**: profile adapter and validate-only API; no browser.
4. **Account/checkpoint PR**: external-account registry, dedicated-mailbox
   connection and polling broker, automatic verification/recovery behavior,
   queue rules, and typed checkpoints.
5. **Workspace PR**: readiness, queue, run history, and checkpoint interface.
6. **Companion prototype PR**: pairing, claim, heartbeat, local dry run.
7. **Controlled browser PR**: one test form, visible browser, human final gate.
8. **Cloud experiment PR**: isolated worker and authenticated test browser
   stream using fake data only.
9. **Extension spike PR**: shared conformance tests and three representative
   playbook flows, kept experimental.
10. **Deployment/security PRs**: permanent HTTPS, object storage, encrypted
    secrets, signed releases, and operational controls.

Do not build every layer in one giant merge. Each PR should have a clear test
and rollback path.

## Checkpoints To Bring Back To Codex

Stop and ask for help after each checkpoint rather than guessing through an
error:

1. Send the output of the prerequisite version commands.
2. Confirm both local URLs load before linking the runner.
3. Send `git status --short --branch` from both repositories before edits.
4. Confirm the product assumptions at the top of this guide.
5. Review the proposed models with your coworker before generating migrations.
6. Review API ownership/CSRF tests before adding UI.
7. Use only a controlled test form for the first companion browser run.
8. Use fake profiles only for the first cloud/extension experiments.

The validation milestone is complete: Project Exchange can collect and validate
private shared and target-specific answers against every maintained playbook and
show useful readiness errors. Browser execution comes only after this boundary
and encrypted mailbox handling are complete.
