# Getting unstuck — agent playbook

**You are the AI coding agent.** The workshop attendee has hit a problem and asked you to read this doc. Use it to diagnose and fix.

The workshop's hard rule is *no manual actions* — the attendee does not edit files or run commands; you do. So when you find the issue, fix it. Don't ask permission for routine fixes. Act, then summarize what changed in one or two sentences.

---

## How to use this doc

1. Read the attendee's last message — the error, the symptom, what they saw.
2. Find the section below that matches. Sections are grouped by exercise plus a general triage section.
3. Run the **diagnostic** to confirm. If it doesn't match, scan adjacent sections — symptoms can overlap.
4. Apply the **action**. Update files in place. Run any commands needed.
5. Report back: what was wrong (one sentence), what you did (one sentence), what to verify next (one sentence). No apologies, no lectures.

If nothing here matches, see the [last section](#nothing-matches) for fallback steps.

---

## Cassandra registration — manual step the install can't do

After the installer prints `[STEP 7/7] Installation Complete!`, **the attendee must register Cassandra in the watsonx.data UI by hand**. The dev edition doesn't expose an API for this. If federated queries from Presto into Cassandra fail with "no such schema/catalog `cassandra_catalog`," this step was likely skipped or done with wrong values.

Registration is a **two-part** step: (1) add the Cassandra database (which creates the `cassandra_catalog` tile), and (2) associate that catalog with the Presto engine and restart the engine. Skipping part 2 is the most common failure mode — the database shows up in the UI, the attendee says "done," but Presto still can't see the catalog.

**Symptom (in code/queries):** Presto queries like `SELECT * FROM cassandra_catalog.workshop.customers` fail with `Schema 'cassandra_catalog.workshop' does not exist`, `Catalog 'cassandra_catalog' does not exist`, or hang past 60s with no error.

**Diagnostic:**

1. Ask the attendee to open `https://localhost:9443` and check **Infrastructure Manager → Databases**. If `cassandra_workshop` isn't listed, registration was never done. If it's listed but the catalog name doesn't match `cassandra_catalog`, the form was filled wrong.
2. If the database *is* listed, ask the attendee to look at the **Catalogs** row in Infrastructure Manager: is the `cassandra_catalog` tile connected (line drawn) to the `presto-01` engine tile? No line = the catalog was never associated.
3. Check whether the Presto engine is showing a **restart-required** indicator or anything other than **Running**. If the association was added but the engine wasn't restarted, Presto still doesn't see the catalog.

**Action — direct the attendee through both parts:**

> "Open `https://localhost:9443`. Log in as `ibmlhadmin` / `password`. Go to **Infrastructure Manager → Databases → Add database**. Pick **Apache Cassandra** and enter exactly:
> - Display name: `cassandra_workshop`
> - Hostname: `host.containers.internal`
> - Port: `9042`
> - Username: `cassandra`
> - Password: `cassandra`
> - Catalog name: `cassandra_catalog`
>
> Click **Test connection** (it should succeed), then **Add**. That creates a `cassandra_catalog` tile under **Catalogs** in Infrastructure Manager.
>
> Then — *this is the step people skip* — hover the new `cassandra_catalog` tile, click the **🔗 Manage associations** icon at the top-right of the tile, pick the `presto-01` engine, and **Save**. The Presto engine tile will then show a restart-required indicator; click it (or use the engine's **⋯ menu → Restart**) and wait for the engine to return to **Running** (~30–60s)."

After they confirm both parts and the engine is back to Running, retry the failing query. If it still fails, double-check the catalog name (**Databases** → click the entry; the catalog must read `cassandra_catalog` exactly), and confirm the association line is drawn from `cassandra_catalog` to `presto-01` in Infrastructure Manager.

### Browser refuses to load `https://localhost:9443`

**Symptom:** the attendee opens `https://localhost:9443` and the browser shows `NET::ERR_CERT_AUTHORITY_INVALID` (or similar) with **no "Advanced → Proceed to localhost (unsafe)" link** — just a hard block. Common on corp-managed Edge / Chrome where strict-cert policies are enforced or HSTS is preloaded for `localhost`.

**Diagnostic:** ask the attendee whether they see an **Advanced** button on the warning page. If yes, this isn't the bug — they should click through. If there's no button at all, the browser is blocking the bypass.

**Action — try in this order:**

1. In Chrome / Edge, navigate to `chrome://flags/#allow-insecure-localhost` (or `edge://flags/#allow-insecure-localhost`), enable it, restart the browser, and retry. This re-enables the bypass for `localhost` only.
2. Try Firefox — its self-signed-cert handling on `localhost` is more permissive than corp-managed Chromium.
3. If neither works (corp policy is preventing the flag from sticking), the attendee can use `curl -k https://localhost:9443/lakehouse/api/v3/ready` to confirm the service is up and continue the workshop without the UI — most queries the agent runs will go through the Presto HTTP API anyway, not the UI. The one step that genuinely requires the UI is registering Cassandra; without UI access, the attendee can't complete that step on a corp box.

---

## General — verifying your own output

Before declaring something done, run these three cross-checks. If any fail, fix before reporting.

- **Table names exist.** Every table referenced in `spec/design.md`, generated SQL, or code must appear verbatim in [`SCHEMAS.md`](../SCHEMAS.md) or the per-domain `cassandra_schema.cql` / `iceberg_schema.sql`. Common hallucinations to grep for: `customer_dim`, `sales_fact`, `daily_metrics`, `customer_cohort_analysis`. None of those exist in this workshop.
- **REQ-IDs covered.** Every REQ-ID in `spec/requirements.md` must appear in at least one endpoint description in `api/openapi.yaml`. Conversely, every endpoint must trace back to at least one REQ.
- **Tests match the spec, not the implementation.** Tests assert what `openapi.yaml` says the response should be. If the implementation differs, the implementation is wrong, not the test. Never weaken an assertion to make a test pass; if you genuinely believe the spec is wrong, update `openapi.yaml` first and explain why.

---

## Exercise 1 — Requirements

### Vague, untestable REQs

**Symptom:** REQs use fuzzy adjectives — "fast", "reliable", "easy", "good", "scalable" — that no one could write a test from.

**Diagnostic:** scan `spec/requirements.md`. List each REQ containing a fuzzy term or that lacks acceptance criteria specific enough to write a one-sentence test.

**Action:** rewrite each fuzzy REQ as concrete and measurable. Example: "the system is fast" → "REQ-007: List endpoints return within 2 seconds at the 95th percentile." Update the file in place.

### Implementation leaking into requirements

**Symptom:** `requirements.md` mentions databases (Cassandra, Iceberg, Postgres), frameworks (FastAPI, Express, React), HTTP methods, JSON, libraries, or any other technical detail.

**Diagnostic:** grep `requirements.md` for: cassandra, iceberg, presto, fastapi, express, react, json, http, get, post, sql, api, database, query, table, endpoint.

**Action:** strip every match. Requirements describe what the user sees, not how it's built. Update in place.

### Scope is too big for the time budget

**Symptom:** more than ~10 REQs, or REQs whose combined implementation clearly exceeds 60 minutes of build time.

**Diagnostic:** the workshop has a 60-minute build budget for Exercise 3, with three required endpoint types (one Cassandra read, one Iceberg read, one federated read). Estimate which REQs are essential for that minimum vs. nice-to-have.

**Action:** keep 5–7 REQs in scope. Move the rest into the existing `## Out of scope` section, or create one. Tell the attendee which REQs you moved and why.

### Attendee hasn't given you enough to write requirements

**Symptom:** the prompt was "write requirements for an e-commerce app." Not enough specificity.

**Diagnostic:** check whether you know who uses this, what they do, what success looks like.

**Action:** flip the relationship. Tell the attendee you're going to interview them. Ask one question at a time about persona, primary flow, and success criteria. After 5–7 questions, write the requirements.

---

## Exercise 2 — Spec (design + OpenAPI)

### Hallucinated tables in design.md

**Symptom:** `spec/design.md` references tables not present in the workshop's loaded schemas.

**Diagnostic:** re-read `SCHEMAS.md` and the two DDL files for the attendee's domain. Extract every table name from `design.md`. Compare.

**Action:** for each invented name, find the closest real table in the schema and substitute. If the design references a concept the real schema doesn't support, tell the attendee — don't fabricate a workaround. Update `design.md` in place.

### No actual federated query

**Symptom:** the design has separate Cassandra endpoints and separate Iceberg endpoints but no endpoint that joins them in a single Presto query.

**Diagnostic:** grep `api/openapi.yaml` and `design.md` for explicit mentions of joining `cassandra_catalog.<domain>.X` to `iceberg_data.<domain>.Y`. If absent, federation is missing.

**Action:** add the missing federated endpoint. Write the actual SQL in `design.md` — it should reference both `cassandra_catalog` and `iceberg_data` schemas in the same FROM/JOIN clause. The federated query is the point of the workshop.

### Missing REQ coverage

**Symptom:** some REQ-IDs are not covered by any endpoint in `openapi.yaml`.

**Diagnostic:** list every REQ-ID in `requirements.md`. For each, find covering endpoints. Flag uncovered REQs.

**Action:** for each uncovered REQ, either add a covering endpoint OR move the REQ to out-of-scope (with a one-sentence reason). Update both files. Don't silently drop REQs.

### OpenAPI without examples

**Symptom:** response schemas in `openapi.yaml` have no `examples:` blocks.

**Diagnostic:** grep `openapi.yaml` for `examples:`.

**Action:** for every response schema, add an `examples:` block with realistic data — actual numbers, dates, IDs that match what the schemas in `SCHEMAS.md` describe. These become test fixtures in Exercise 3.

### Attendee wants to switch stacks mid-design

**Symptom:** "I picked language X but I don't know it; can we switch?"

**Diagnostic:** confirm whether they want to switch because the original choice is genuinely blocking them, or because they're nervous about an unfamiliar language.

**Action:** if they're just nervous, push back gently — the workshop's pitch is that they don't need to read the code, they steer the loop. Suggest one cycle in the original stack first. If they insist, switch the stack note in `design.md` and adjust any sketched code or library references. Don't restart the design from scratch.

---

## Exercise 3 — Tasks + build

### Connection errors (Cassandra / Presto / watsonx.data)

**Symptom:** "Connection refused", SSL / cert errors, "host not found", wrong port.

**Diagnostic:** check the connection-details section of `SCHEMAS.md`. Common mistakes:
- Code uses `host.containers.internal:9042` from the host machine — should be `localhost:9042`.
- Presto client is verifying the self-signed certificate — needs to disable verification.
- Wrong port: Presto is `8443`, Cassandra is `9042`, watsonx.data REST is `9443`.

**Action:** locate the connection setup in the relevant client / config file. Update host, port, and TLS settings to match SCHEMAS.md. Re-run the relevant test.

### Test failure followed by temptation to weaken the test

**Symptom:** test fails; first instinct is to change the assertion to match the implementation.

**Diagnostic:** read what `openapi.yaml` says the response shape should be. Compare to what the implementation returns. Compare to what the test asserts.

**Action:** if test matches the spec, the implementation is wrong — fix the implementation. If you genuinely believe the spec is wrong, update `openapi.yaml` first, explain why to the attendee, then update both implementation and test. Never silently weaken assertions.

### Federated query times out

**Symptom:** the Presto query joining Cassandra and Iceberg hangs or returns no rows.

**Diagnostic:** read the SQL. Check whether it filters on partition columns of the Iceberg side (look at the `PARTITIONED BY` clause in the relevant `iceberg_schema.sql` — typically `year` and `month`). Check for accidental cross joins (a JOIN missing an ON clause).

**Action:** add a partition filter and a proper join condition. Re-run.

### Backend runs but UI shows no data

**Symptom:** UI loads, fetches show errors or empty responses.

**Diagnostic:** look at the browser network tab output the attendee pasted. Common causes: CORS misconfigured on the backend, frontend hitting wrong URL, backend returning 500 with a swallowed error.

**Action:** fix CORS config / fetch URL / unhandled exception. Tell the attendee what broke and what you changed.

### You're stuck in a loop

**Symptom:** you've made the same fix two or three times and the same error returns. You've lost the plot.

**Diagnostic:** stop editing. Re-read three files cold: `spec/requirements.md`, `api/openapi.yaml`, and the implementation file in question.

**Action:** before any more code changes, write to the attendee in plain English: what does the spec say should happen, what does the code actually do, and where's the gap. Wait for them to confirm the diagnosis before resuming edits.

### Attendee is running out of time

**Symptom:** less than 15 minutes left and the app isn't working end-to-end.

**Diagnostic:** identify which endpoints work (if any) and which are broken.

**Action:** triage. Get one endpoint — pick the simplest, usually the Cassandra read — working end-to-end through the UI. Skip the rest. Tell the attendee you're cutting scope and what's still on the table for Hour 4. A working app with one endpoint demos better than a half-working app with three.

---

## Hour 4 — expansion stuck points

### Adding a new REQ but the propagation skipped a file

**Symptom:** the attendee asked you to add a new REQ end-to-end. You added the endpoint and code but missed `requirements.md` or `todo.md` or the test.

**Diagnostic:** the propagation chain is `requirements.md` → `openapi.yaml` → `todo.md` → code → test → UI. Verify each file changed.

**Action:** complete the chain. Don't take shortcuts — the demo of Hour 4 is the propagation itself.

### Iceberg time-travel returns nothing

**Symptom:** time-travel query returns empty results or "snapshot not found."

**Diagnostic:** check available snapshots: `SELECT snapshot_id, committed_at FROM <catalog>.<schema>.<table>$snapshots ORDER BY committed_at`. The workshop's data may have only one snapshot (the initial load), in which case time travel against "yesterday" won't show anything different.

**Action:** if only one snapshot exists, generate a second one by inserting or updating a row, then re-run the time-travel query against the earlier snapshot. Tell the attendee what you did so they understand the demo.

### Schema evolution + existing query

**Symptom:** added a column to an Iceberg table; existing queries fail or new queries don't see the column.

**Diagnostic:** confirm the `ALTER TABLE ... ADD COLUMN` ran successfully (check via `DESCRIBE`). Existing queries should continue working — they don't reference the new column. New queries must explicitly select the new column or use `SELECT *`.

**Action:** if existing queries broke, the column add was wrong (e.g., the column type conflicts). Roll back via `ALTER TABLE ... DROP COLUMN` and try again with a compatible type.

---

## Nothing matches

If the symptom doesn't match any section above:

1. Tell the attendee, in plain English: "I read getting-unstuck.md and didn't find a matching pattern. Here's what I see: [the symptom]. Here's what I think is happening: [hypothesis]. I want to try [approach] — can you confirm?"
2. Wait for the attendee to confirm before making changes.
3. If the attendee gives you the go-ahead, attempt the fix and report back.
4. If the same approach fails twice, tell the attendee to ask the instructor — this is the genuinely-novel category.

---

## Things you should not do

- Edit files the attendee did not ask you to touch.
- Apologize at length. One sentence is enough; act, don't grovel.
- Lecture the attendee about best practices unsolicited.
- Silently weaken tests or hide errors to "make it work."
- Invent table names, endpoint shapes, or schema fields not present in the workshop's actual data.
- Suggest containerization, deployment, CI/CD, or observability — those are out of scope for this workshop.
