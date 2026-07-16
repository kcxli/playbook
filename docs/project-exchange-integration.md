# Project Exchange Integration Plan

## Status

This is the agreed direction and current implementation record. A first
validation-only foundation now exists locally on Project Exchange branch
`feature/auto-apply-foundation`; no code has been merged into
`SharpDressedMan/project-exchange` `main` yet.

The foundation includes an in-memory runner validation API, immutable playbook
manifest/hash checks, a runner-owned canonical intake contract, owner-scoped
Django profile/mailbox metadata, position-scoped answer sets, an authenticated
readiness endpoint, and applicant forms for shared and per-position answers.
All maintained playbooks carry public listing metadata and can be synced
idempotently into Project Exchange; Auto Apply actions appear on the postings
list, timeline, applicant match cards, and position details. It does not start
Playwright or submit an application.

For concrete local setup commands and the recommended pull-request sequence,
see the [beginner integration guide](project-exchange-beginner-guide.md).

## Confirmed Product Decisions

1. `project-exchange` is the deployed product and control plane. It owns user
   accounts, private applicant profiles, documents, job targets, permissions,
   run history, and the React experience.
2. `project-playbook` remains the deterministic automation engine and trusted
   playbook catalog. It does not become frontend code.
3. Runtime AI recovery is sunset. Application runs never call an AI model.
4. During testing, every final submission requires the applicant's own click.
   All maintained playbooks end with `pause_for_user`, and live headless runs
   cannot pass that gate.
5. Every applicant may use the product for their own applications. Applicants
   do not edit or upload executable playbooks, JavaScript actions, equivalence
   tables, runner packages, or backend code. Maintainers review and publish
   those assets.
6. Automatic final submission may be designed later as an explicit, consented,
   guarded mode. It is not enabled by removing the current pause or
   uncommenting a playbook step.
7. Auto Apply is offered only for positions listed by Project Exchange and
   mapped to a maintainer-reviewed, immutable playbook release. Expect a few
   hundred distinct supported positions each annual hiring cycle, with new
   playbooks arriving daily or weekly during the busy period.
8. A run creates an external ATS account when no suitable account exists, then
   reuses that account for later positions sharing the same account scope. A
   single dedicated application email cannot normally register a fresh account
   for every posting on the same ATS or university site.
9. Email-link and email-code verification is automatic during normal runs.
   Copying a link/code is recovery-only, not the default experience. Applicants
   create and retain access to a dedicated job-application mailbox, then grant
   Project Exchange access to it. That exact address is used for ATS accounts;
   the current developer IMAP environment variables are not the production
   credential design. Gmail is the only mailbox provider required for the first
   pilot.
10. CAPTCHA and other unavoidable human challenges pause the run, notify the
    applicant, preserve the browser session, and resume after the applicant
    completes the challenge. They are never bypassed.
11. One versioned playbook contract should support three execution experiments:
    a desktop companion as the reliability baseline, a cloud worker as the
    zero-install prototype, and a smaller Chrome/Edge extension feasibility
    test.

## Recommended Architecture: One Control Plane, Replaceable Executors

For the stated goal - thousands of applicants worldwide, each using the product
for themselves and personally performing the final click - keep execution mode
out of the Django product contract. Start with the local companion for
reliability, but make a cloud worker and extension able to consume the same run
snapshot and report the same events.

```text
Cloud: Project Exchange

React UI <---- HTTPS ----> Django API ----> PostgreSQL
                              |                 |
                              +---- Redis ------+
                              |
                              +---- private object storage
                              |
                       signed run snapshot
                              |
             +----------------+----------------+
             |                |                |
             v                v                v
    Desktop companion    Cloud worker     Extension experiment
    Python + Playwright  isolated browser  Chrome/Edge executor
             |                |                |
             +----------------+----------------+
                              |
                              v
                    university/employer ATS
                              |
                  applicant handles checkpoints
                    and clicks final submit
```

The website coordinates every run. The baseline companion runs Chromium on the
applicant's Windows, macOS, or Linux computer and makes outbound authenticated
requests to Django. The cloud prototype runs an isolated browser in Project
Exchange infrastructure and streams it to the applicant for checkpoints and
review. The extension experiment tests whether Chrome/Edge can execute the same
semantics without a native application.

## What "Where Does Playwright Run?" Means

Playwright controls a real browser process. That process must physically run
somewhere:

- A cloud worker runs the browser in your infrastructure. It is the only true
  zero-install option, but requires browser streaming, strong per-run
  isolation, cloud capacity, secure credential handling, and a plan for sites
  that challenge data-center IP addresses.
- A local companion runs the browser on the applicant's computer. The person
  can see the form, complete human checkpoints, use their own network, and
  perform the final click. Browser compute is distributed across user devices.
- A browser extension runs in the applicant's existing Chrome/Edge session. It
  is a smaller install, but needs a second executor implementation, broad site
  permissions, reliable upload/popup handling, and a distribution design that
  complies with browser-store rules for remotely supplied logic.

A normal React webpage cannot launch this Python process, control Playwright,
or freely access local documents because it runs inside the browser sandbox.
It also cannot control an unrelated university tab. From the applicant's point
of view cloud execution stays inside the browser, but the controlled browser is
actually running on a server and is displayed as a secure live stream.

## Shared Executor Contract

Do not make Django endpoints specific to Playwright or one operating system.
Every executor receives the same immutable run snapshot:

- applicant, target, profile, document, and external-account snapshot ids;
- runner schema version and exact playbook release/hash;
- approved starting URL and navigation-domain allowlist;
- submission policy and required executor capabilities;
- short-lived, owner-scoped document grants; and
- an opaque run credential that cannot claim another run.

Every executor emits the same ordered event and checkpoint vocabulary. At
minimum include `queued`, `claimed`, `running`, `awaiting_email`,
`waiting_for_user`, `review_ready`, `failed`, `cancelled`, and `completed`.
This boundary lets Project Exchange test cloud execution without rewriting the
website and test an extension without forking the playbook format.

## Cloud Runner Prototype

The zero-install prototype should run one browser per application in a
non-root, sandboxed, short-lived container. It should receive only one run's
data, expose no database credential, use short-lived document URLs, and be
destroyed after completion or timeout.

When a CAPTCHA or final review is reached, Project Exchange opens an
authenticated live-browser session. The applicant interacts with the actual
university page through that stream. The worker must enforce a checkpoint
timeout and cleanly report abandonment; a paused cloud browser cannot consume
resources forever.

Do not assume the number of playbooks equals execution volume. A few hundred
listed positions can produce many thousands of applicant runs. Measure peak
concurrency, run duration, CAPTCHA frequency, data-center-IP blocks, and cost
before treating cloud execution as the default.

## Browser Extension Experiment

The extension is an experiment, not a second production engine yet. Test it in
desktop Chrome/Edge against three representative playbooks: a simple form, an
upload-heavy flow, and a popup/multi-domain flow.

Chrome Manifest V3 does not generally permit an extension to fetch and
interpret complex remote commands. The `userScripts` API is a possible
technical route for dynamic logic, but requires an additional user-controlled
permission toggle and still needs store-policy review. Do not promise extension
delivery until upload behavior, navigation permissions, dynamic playbook
distribution, and Chrome Web Store acceptance are demonstrated.

## Local Companion Responsibilities

The companion is an end-user application, not a developer checkout. It should:

- pair with one Project Exchange account and register a revocable device;
- poll or wait for that user's signed run assignments;
- verify the runner/playbook release and allowed application domain;
- download only the profile snapshot and documents needed for that run;
- validate the playbook and data locally before opening a browser;
- launch a visible, dedicated browser profile rather than the person's everyday
  Chrome profile;
- execute deterministic actions and send sanitized status events;
- pause for CAPTCHA, 2FA, missing answers, and `pause_for_user`;
- leave the final submit button to the applicant;
- delete temporary profile data, documents, and artifacts according to the
  retention policy; and
- update through a signed release channel.

For the first version, HTTPS polling is simpler than a persistent WebSocket:
the companion asks for work, claims one run atomically, posts events, and
heartbeats while it is active. WebSockets can improve responsiveness later
without changing the ownership boundary.

## External Accounts And Verification Email

Account creation is part of automation, not a manual prerequisite. Model it as
`ensure external account`, not `always create a new account`:

1. Resolve an account scope such as a global ATS, university tenant, or
   institution-specific application domain.
2. Reuse the applicant's active account for that scope when one exists.
3. Otherwise generate a unique strong password, create the account through the
   playbook, and record the successful account only after registration is
   confirmed.
4. Make the credentials recoverable by their owner. Never reuse one password
   across unrelated ATS accounts.

Normal verification should preserve the existing `await_email_link` and
`await_email_code` semantics behind an automatic mailbox broker:

1. The applicant creates a dedicated Gmail account used only for job
   applications, keeps their own login, and connects it to Project Exchange
   during onboarding.
2. The exact applicant-owned mailbox address is used to create university/ATS
   accounts. Project Exchange does not replace it with an alias or forwarding
   address.
3. The private prototype uses a revocable Gmail app password over IMAP because
   the runner already supports that path. It never asks for the normal Google
   password. Before a public pilot, replace this onboarding with a Google OAuth
   `Connect Gmail` flow and request only the mailbox-read capability required
   for verification.
4. Before requesting a verification message, the run registers the expected
   recipient, sender/subject hints, allowed link domains/pattern, and start time.
5. The mailbox broker authenticates just in time, examines only messages that
   could match the active expectation, extracts the expected link/code in
   memory, and delivers only that value to the authorized executor.
6. The executor opens the allowlisted link in the existing automation session
   or fills the code, then resumes without applicant action.
7. Ordinary interview, status, and recovery messages stay in the dedicated
   mailbox, where the applicant can read and manage them normally.

The dedicated mailbox is effectively a root credential: anyone who controls it
may be able to reset every ATS account created with it. Store its OAuth refresh
token, app-specific password, or supported provider credential only through an
audited secret-management service with encryption at rest and narrowly scoped
decryption. Only the mailbox broker should receive the secret, and only for the
duration of a polling operation. Do not put it in a normal database field,
Redis job, executor snapshot, browser UI, log, analytics event, or support tool.

The applicant may deliberately authorize broad mailbox access, but Project
Exchange only needs to read messages; it should not send, delete, archive, or
change account settings. Provider authentication still constrains the product:
Gmail app passwords require 2-Step Verification and are unavailable for some
accounts, while Gmail server-side read scopes can require restricted-scope
OAuth verification and a security assessment. Complete that Google approval
work before onboarding public users. Outlook and other providers are outside
the first pilot and can be added later through the same mailbox-broker contract.

Manual one-use code/link entry remains an authenticated recovery path for an
unmatched or delayed message. It expires quickly and is never written to events,
logs, analytics, screenshots, or long-term storage. The current global
`IMAP_*` environment variables remain local-development-only; a production IMAP
connection must use a per-user encrypted secret, provider-specific validation,
revocation, and audit controls.

Once profile and email onboarding are complete, the intended position flow is
one Auto Apply click until an unavoidable CAPTCHA/attestation or final review.
Initial onboarding itself is not literally one click: the applicant must provide
their private application data/documents, create a dedicated mailbox, and
authorize Project Exchange to read it.

### Current Account-Flow Gaps

The maintained playbooks express the intended account-creation behavior, but
they are not yet uniformly ready for this product contract:

- UCI currently enables a returning-user password path while its first-time
  email-verification path is commented out.
- UCSB and CUHK actively depend on developer-supplied IMAP credentials.
- Utah and NYU Langone encounter CAPTCHA/manual interaction that is not yet a
  typed resumable checkpoint.
- several playbooks check terms, certifications, privacy statements, or
  attestations automatically; each must be classified as safe automation or an
  explicit human checkpoint before publication; and
- authenticated/TODO sections in individual playbooks must remain unsupported
  until verified against the live form.

Do not display Auto Apply merely because a YAML file exists. A target becomes
supported only after its full first-time account flow, verification behavior,
uploads, required questions, checkpoint locations, and final human gate pass a
release checklist.

## Human Checkpoints And Notifications

`pause_for_user` must evolve from a terminal prompt into a typed checkpoint.
Checkpoint reasons should include `captcha`, `legal_attestation`,
`email_attention`, `unexpected_site_prompt`, and `final_review`.

Each checkpoint records a safe message, creation/expiry timestamps, executor
session, and optional resume condition. The executor stops before the protected
action and continues only after the owner resumes it and the expected page
condition is satisfied.

Notification behavior depends on execution mode:

- companion: foreground the dedicated browser and send an OS notification;
- cloud: notify in Project Exchange and open the authenticated live browser;
- extension: focus the application tab and show a browser notification/badge.

Browser push or email can notify a user who has left Project Exchange, but no
notification contains applicant answers, passwords, or one-time links.

## Applicant And Maintainer Permissions

Applicants may:

- edit their own private profile and application answers;
- upload and select their own documents;
- choose a supported job target;
- start, pause, cancel, and resume their own runs;
- view only their own sanitized events and private artifacts; and
- review and submit their own application in the local or streamed browser.

Applicants may not:

- edit or upload YAML playbooks;
- provide JavaScript for the `script` action;
- alter selectors, equivalence aliases, package versions, or allowed domains;
- claim another user's run or artifacts; or
- send arbitrary commands to any executor.

Maintainers author playbooks from extractor evidence, test them against fake
profiles, review code changes, and publish a versioned release. The backend
assigns only a trusted playbook identifier, version, hash, and signed manifest.
Every executor rejects a modified or unrecognized bundle.

This is what "maintainer-only playbooks" means: everyone can use the feature,
but using it is different from programming it.

## End-To-End Run Lifecycle

1. The applicant signs into Project Exchange, completes the private application
   profile, registers/verifies a dedicated application mailbox, and pairs a
   companion only when local execution is selected.
2. The applicant clicks Auto Apply on a supported position. Readiness checks
   have already ensured the required answers and documents exist.
3. Django validates ownership and readiness, records an immutable profile
   snapshot, and creates an `ApplicationRun` in `queued` state.
4. The selected authorized executor claims the run. Django returns a
   short-lived run bundle containing trusted identifiers and signed download
   references, not an applicant-supplied command.
5. The executor validates the bundle, resolves or creates the scoped external
   account, creates an isolated run directory/browser session, and starts the
   playbook.
6. It reports step/status events without sending complete answers or secrets to
   logs.
7. Email verification is handled through the mailbox broker. At CAPTCHA,
   attestation, or another human checkpoint, the run enters
   `waiting_for_user`, notifies the applicant, and preserves the session.
8. At `pause_for_user`, the run becomes `review_ready`. Automation stops and
   the applicant inspects the completed form and clicks final submit in the
   local or streamed university browser.
9. The executor detects or receives confirmation, records the outcome, closes
   the browser, and cleans up temporary data.

If a selected companion is offline or closed, the run stays queued or paused.
If a cloud worker disconnects, its lease expires and recovery follows an
explicit executor policy. The backend never silently moves a live browser
session between executors or to another user's device.

## Human Submission Policy

The current repository implements the first testing-stage gate:

- final submit actions are absent or commented in maintained playbooks;
- every maintained playbook ends with `pause_for_user`;
- the standalone CLI keeps the visible browser open while waiting; and
- live `--headless` execution is rejected for a playbook with a human gate.

Before public release, add defense in depth in the companion and release
pipeline: a signed manifest with `submission_mode: human`, static checks for
prohibited final-submit actions, reviewed playbook releases, and an agent that
will not accept an automatic-submit capability.

When automatic submission is considered later, introduce it as a new versioned
policy with explicit applicant consent, audit events, per-run authorization,
and a kill switch. Do not weaken the meaning of `pause_for_user`.

## Scaling To Thousands Of Users

With local execution, Project Exchange scales as a control plane rather than a
farm of thousands of browsers:

- PostgreSQL is the source of truth for ownership, snapshots, runs, and events.
- Redis can provide queue notifications, caching, and realtime fan-out, but run
  state must remain durable in PostgreSQL.
- Each paired device claims only its owner's runs and should start with one
  active browser run at a time.
- Django, API workers, and object storage can scale horizontally without
  hosting every Chromium process.
- Device heartbeats, idempotent claims, leases, retries, and sequence-numbered
  events handle disconnects without running an application twice.
- Per-user and per-site rate limits prevent accidental bursts and protect
  supported application sites.

Applicants may queue hundreds of distinct positions, but the first release
should allow only one active browser run per applicant. Queueing is not the same
as launching hundreds of simultaneous account creations. Add duplicate-target
idempotency, explicit cancellation, queue visibility, per-domain pacing, and a
global kill switch. A future increase in per-user concurrency must be based on
measured site behavior, not only available compute.

Cloud execution adds a separate capacity limit. Bound total workers and
per-domain concurrency, expire unattended checkpoints, and apply backpressure
instead of silently dropping or duplicating runs.

This still requires serious operations work: signed installers and updates,
Windows/macOS/Linux support, observability, data-retention controls, and support
for users whose devices sleep or lose connectivity.

## Private Intake Boundary

`project-exchange` already stores useful applicant information, but its current
profile is designed for public matching. Auto-apply requires a separate private
contract. Do not place addresses, demographics, references, credentials, or
application exceptions into the public `CandidateProfile` or employer-visible
wizard answers.

The implemented adapter mappings include:

| Project Exchange value | Runner value |
|---|---|
| `full_name.first/middle/last/suffix` | `person_name.legal_name.*` |
| `contact_email` | `emails.preferred_contact_email` |
| `pronouns` enum | `identity_and_status.pronouns.set` |
| `current_state` | part of `address_and_contact.primary_address` |
| `work_authorization` enum | work authorization and sponsorship facts |
| `education[]` | `education.schools[]` |
| uploaded `cv` | `documents.resume_path_or_url` |
| uploaded application materials | matching `documents.*_path` fields |

`playbook_runner/intake.py` now declares the private shared fields, canonical
enum values, per-playbook requirements, required documents, and true target
overrides. Project Exchange renders this contract in the applicant workspace
and stores only position referral, institution relationships, or genuinely
unique questions in `ApplicationAnswerSet`. ATS-specific versions of shared
education, employment, demographic, and platform facts are derived by the
runner instead of being asked again. The document model includes teaching
evaluations, references, syllabus, writing sample, and additional attachments.

Mailbox authorization and encrypted secret handling remain incomplete. The
site stores the exact Gmail address and secret-manager reference metadata, but
does not collect a plaintext app password. Government IDs and criminal-history
answers are intentionally blocked from ordinary JSON and require a protected
runtime checkpoint or approved encrypted store.

## Project Exchange Preconditions

Address these before enabling application runs:

1. The current `POST /api/submissions/` view is `csrf_exempt` while still
   attaching a submission to `request.user` when a session cookie is present.
   Require CSRF for authenticated writes, or split anonymous and authenticated
   endpoints.
2. Candidate-profile builds currently use an in-process daemon thread. Replace
   that pattern with durable background jobs; web-process restarts must not
   abandon work.
3. Store private documents in owner-scoped object storage with short-lived
   download grants for one claimed run. A server-local `MEDIA_ROOT` cannot
   directly serve worldwide companion devices.
4. Add strict owner checks to every profile, target, run, event, artifact,
   device, cancellation, claim, and resume endpoint.
5. Keep application-profile data private by default. Existing public field
   visibility controls are not a substitute for a private application contract.

## Django Models To Add

Names are illustrative; migrations belong in `project-exchange`.

### `ApplicationProfile`

- One private, versioned profile per applicant.
- Validated against a formal runner profile schema.
- Separate from public profile/matching data.
- Stores facts, defaults, exceptions, and references, but no plaintext secrets.

Starting with a validated `JSONField` is reasonable because the contract is
nested and still evolving. Frequently queried fields can be normalized later.

### `ApplicationAnswerSet`

- One owner-and-target scoped nested answer map per listed position.
- Stores only declared `position_overrides.*` fields for referral,
  institution relationships, and genuinely unique application prompts.
- Never stores mailbox credentials, government IDs, or criminal-history data.
- Merged after the shared profile only for its own target.

### `AutomationDevice`

- Applicant owner, device id, platform, companion version, and last heartbeat.
- Hashed device credential or registered public key.
- Pairing, active, expired, and revoked states.
- Never stores a reusable pairing code in plaintext.
- Required only for companion execution; a cloud worker is a service identity,
  not an applicant device.

### `ApplicationTarget`

- Maintainer-owned mapping from one listed posting to an external application.
- Employer/playbook key, external URL, job identifier, approved domains, and
  immutable playbook version/hash.
- Active/disabled state, last verified time, required capabilities, and a safe
  reason when Auto Apply is unavailable.

### `ExternalApplicationAccount`

- Applicant owner and normalized account scope such as ATS tenant/domain.
- Dedicated application email, username, encrypted credential reference,
  creation status, and last successful use.
- One unique generated password per account scope; no plaintext secret in model
  fields, logs, events, or snapshots.
- Supports create, active, recovery-required, and disabled states.

### `ApplicationMailbox`

- Applicant owner, exact applicant-owned address used by ATS accounts,
  provider/protocol, connection method (`oauth`, `imap_app_password`, or an
  explicitly supported provider credential), status, and last health check.
- Stores only an opaque encrypted-secret reference and optional granted scopes;
  never a mailbox password, app password, or OAuth refresh token in a normal
  model field.
- The applicant retains direct mailbox access. Disconnecting or revoking the
  credential immediately prevents new verification polling.

### `EmailVerificationExpectation`

- Run/mailbox owner, expected recipient, sender/subject hints, allowed link
  domains/pattern, creation time, expiry, and pending/matched/expired state.
- Can be matched only once and only while the owning run is leased in
  `awaiting_email`.
- Stores no plaintext verification code/link after delivery to the executor.
- Ambiguous, failed-authentication, spam, or malware messages never resume a
  run; they trigger a safe recovery notification instead.

### `ApplicationRun`

- Target, applicant, executor mode, claimed device/worker, lease, timestamps,
  external-account snapshot, selected documents/overrides, and current step.
- Suggested statuses: `draft`, `validating`, `queued`, `claimed`, `running`,
  `awaiting_email`, `waiting_for_user`, `review_ready`, `failed`, `cancelled`,
  and `completed`.
- Exact runner version, playbook hash, profile snapshot hash, submission mode,
  and idempotency key.

### `HumanCheckpoint`

- Run owner, typed reason, safe prompt, executor session reference, state,
  created/expiry/resumed timestamps, and optional resume-condition metadata.
- Resume and cancel operations require the same run owner and valid run lease.
- Does not store CAPTCHA answers, verification codes, or sensitive page data.

### `ApplicationEvent`

- Run-scoped monotonic sequence number, event type, step number, safe message,
  and timestamp.
- Metadata must be sanitized; never include passwords or complete profile data.

### `ApplicationArtifact`

- Owner-scoped record for screenshots, page HTML, failure reports, and
  equivalence gaps.
- Local by default during early testing; upload only when needed and authorized.
- Private object storage, short-lived download URLs, encryption, and retention
  limits when server upload is enabled.

## API Shape

An initial API can remain small:

```text
POST /api/automation-devices/pairing-codes/
POST /api/automation-devices/pair/
POST /api/automation-devices/<id>/heartbeat/
POST /api/application-targets/<id>/validate/
POST /api/application-targets/<id>/runs/
GET  /api/application-runs/<id>/
GET  /api/application-runs/<id>/events/
POST /api/application-runs/<id>/cancel/
GET  /api/application-runs/<id>/checkpoints/current/
POST /api/application-runs/<id>/checkpoints/<checkpoint_id>/resume/

POST /api/mailboxes/
POST /api/mailboxes/<id>/connect/
POST /api/mailboxes/<id>/connect-oauth/
GET  /api/mailboxes/oauth/callback/
POST /api/mailboxes/<id>/test/
POST /api/mailboxes/<id>/disconnect/

POST /api/application-runs/<id>/email-expectations/
POST /api/internal/mailbox-expectations/claim/
POST /api/internal/mailbox-expectations/<id>/match/

POST /api/companion/runs/claim/
POST /api/companion/runs/<id>/heartbeat/
POST /api/companion/runs/<id>/events/
POST /api/companion/runs/<id>/complete/

POST /api/internal/cloud-runs/claim/
POST /api/internal/cloud-runs/<id>/events/
POST /api/internal/cloud-runs/<id>/session/
```

Use separate applicant-browser, companion-device, and internal cloud-worker
authentication classes. Every executor endpoint validates executor identity,
run ownership, lease, state transition, payload schema, and idempotency.

## Credentials And Private Data

- Never put ATS passwords, mailbox credentials, session cookies, or document
  contents in logs, Redis payloads, React state, or analytics.
- Generate a different strong password for each external account scope. The
  applicant must be able to recover or export credentials for accounts created
  on their behalf.
- Prefer the operating system credential store for secrets used only by the
  local companion. Shared companion/cloud/extension support requires an audited
  server-side encryption or secret-management service with short-lived access.
- Prefer provider OAuth or a revocable app-specific password. If an explicitly
  supported provider requires another user-authorized credential, encrypt it as
  a secret and never expose it to an executor. Restrict mailbox reads to active
  verification expectations, retain the minimum metadata, and keep manual
  code/link entry as recovery-only.
- Download documents with one-run, short-lived grants into an owner-only
  temporary directory and delete them after the retention window.
- Give every run a dedicated browser profile and artifact directory. Do not
  attach automation to the applicant's normal Chrome profile in the first
  version.
- Upload failure artifacts only with clear disclosure because screenshots and
  page HTML can contain sensitive applicant data.

## Package And Release Strategy

Do not copy runner files into Django. Use the Python package defined by this
repository in three places:

1. The Django/background-job environment may install a pinned version for
   parser and dry-run validation only; it does not need Chromium.
2. The signed local companion bundles the exact runner version, Playwright
   browser version, and trusted playbook release used for live execution.
3. The cloud-worker image pins the same Python runner and Playwright browser
   versions and runs each application in an isolated container.

An extension cannot import the Python engine. Its experiment must implement the
same schema/action semantics and pass a shared conformance suite. Do not retain
two production executors unless the experiment proves the maintenance cost and
store-distribution constraints are acceptable.

Production workers and companions must not mutate installed aliases. Point
`PLAYBOOK_CUSTOM_EQUIVALENCES` at a reviewed, read-only overlay. Promote a gap
during maintenance, review it, run the full matrix, and publish a new release.

## Recommended Delivery Order

1. Keep the current deterministic runner and human gate green in CI.
2. Completed: formalize the private intake contract and canonical choices.
3. Completed: add private profile, target, mailbox metadata, and target-answer models.
4. Completed: build validation-only adapters, forms, and readiness endpoints.
5. Add run, event, checkpoint, device, and external-account models, then the
   dedicated-mailbox connection and polling broker, automatic verification and
   recovery behavior, and typed checkpoint state machine.
6. Build a developer-only companion that claims one test run and exercises one
   non-submitting playbook against a controlled form.
7. Add device pairing, leases, heartbeats, cancellation, reconnect handling,
   and one-active-run queueing.
8. Build a one-playbook cloud worker with an authenticated live-browser view;
   measure reliability and resource use rather than assuming viability.
9. Build a bounded Chrome/Edge extension spike against the shared conformance
   suite and representative forms.
10. Add the applicant readiness, queue, status, notification, checkpoint, and
    review experience.
11. Build signed companion installers and automatic updates for the first two
    supported desktop operating systems.
12. Security-review the complete path, then roll out one ATS family at a time.

## Decisions That Can Wait

The product direction is now clear. These implementation choices should be made
as executor work begins:

- first supported desktop OS;
- desktop packaging and signed-update framework;
- HTTPS polling versus WebSocket timing;
- operating-system keychain integration;
- local artifact retention and opt-in upload policy;
- Google OAuth consent-screen, restricted-scope verification, and security
  assessment timing before the public pilot;
- mailbox secret-management, polling, rate-limit, and revocation design;
- cloud worker provider/autoscaling technology; and
- whether the extension experiment merits a supported production executor.

## Primary Technical References

- [Playwright Python library](https://playwright.dev/python/docs/library)
- [Playwright browser launch and persistent contexts](https://playwright.dev/python/docs/api/class-browsertype)
- [Playwright browser installation and channels](https://playwright.dev/python/docs/browsers)
- [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
- [Playwright Docker and remote execution](https://playwright.dev/python/docs/docker)
- [Chrome user scripts](https://developer.chrome.com/docs/extensions/reference/api/userScripts)
- [Chrome Manifest V3 requirements](https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements)
- [Google app passwords](https://support.google.com/accounts/answer/185833)
- [Gmail OAuth scope classifications](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Microsoft Graph mail permissions](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Microsoft Exchange Online basic-authentication deprecation](https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-basic-authentication-exchange-online)
