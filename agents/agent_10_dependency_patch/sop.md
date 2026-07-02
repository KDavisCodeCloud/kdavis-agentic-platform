# SOP — Agent 10: Dependency & Vulnerability Patching

**Version:** 1.0 | **Owner:** Platform / Security | **Tier:** Growth, Enterprise

---

## Purpose

Agent 10 scans a project's dependency manifest against the OSV.dev vulnerability database, identifies packages with known CVEs, and proposes a patch via a pull request with updated version pins. The operator reviews and approves before any code change lands.

This agent **never runs package install commands** (no `npm install`, `pip install`, etc.). It only modifies the manifest file. Your CI pipeline handles installation and testing after merge.

---

## Trigger

**Manual** — post a scan request via the API. Typically triggered from:
- A scheduled cron job (daily dependency scan)
- A GitHub Actions workflow (`on: schedule`)
- A developer running an ad-hoc scan after a CVE disclosure

### Example

```
POST /agents/agent_10_dependency_patch/run
Authorization: Bearer <workspace_token>
Content-Type: application/json

{
  "payload": {
    "repository":    "acme/backend",
    "ecosystem":     "pip",
    "manifest_path": "requirements.txt",
    "ref":           "main",
    "base_branch":   "main"
  },
  "cloud_provider": "aws"
}
```

---

## Payload Fields

**Required:**

| Field | Description |
|---|---|
| `repository` | `"owner/repo"` — the GitHub repository to scan |
| `manifest_path` | Path to the dependency file within the repo (e.g. `requirements.txt`, `package.json`) |

**Optional:**

| Field | Description |
|---|---|
| `ecosystem` | `npm`, `pip`, `go`, `maven`, `ruby`, `cargo` — auto-detected from `manifest_path` filename if omitted |
| `ref` | Git ref to scan (branch, tag, or SHA). Default: `HEAD` |
| `base_branch` | Base branch for the patch PR. Default: `main` |

---

## Ecosystem Auto-Detection

If `ecosystem` is omitted, the agent infers it from the manifest filename:

| Filename | Ecosystem |
|---|---|
| `package.json`, `package-lock.json` | npm |
| `requirements.txt`, `Pipfile`, `pyproject.toml` | pip |
| `go.mod` | go |
| `pom.xml` | maven |
| `Gemfile`, `Gemfile.lock` | ruby |
| `Cargo.toml`, `Cargo.lock` | cargo |

---

## Supported Ecosystems

| Ecosystem | Vulnerability DB | Manifest Parsed |
|---|---|---|
| npm | OSV.dev → npm | `package.json` (dependencies + devDependencies) |
| pip | OSV.dev → PyPI | `requirements.txt` |
| go | OSV.dev → Go | `go.mod` (require blocks) |
| maven | OSV.dev → Maven | `pom.xml` (`<dependency>` elements) |
| ruby | OSV.dev → RubyGems | `Gemfile.lock` (specs section) |
| cargo | OSV.dev → crates.io | `Cargo.toml` ([dependencies] sections) |

---

## Workflow

```
ingest → diagnose (fetch + parse + OSV scan + LLM) → hitl_gate [PAUSE] → execute → complete
```

### 1. Ingest
- Extracts repository, ecosystem, manifest_path, ref, base_branch from payload
- Ecosystem is auto-detected from manifest filename if not specified

### 2. Diagnose
- **Fetch manifest** via GitHub Contents API (requires `GITHUB_TOKEN`)
- **Parse manifest** — extracts `{name, version}` for each dependency
- **OSV scan** — queries OSV.dev for each package (up to 40 packages)
  - Uses OSV.dev's free public API — no API key required
  - Each query: `POST https://api.osv.dev/v1/query` with package name, version, ecosystem
- **LLM analysis** via `.llm/router.py` (`task_type="vulnerability_analysis"`)
  - LLM receives: manifest content, OSV results with CVE details
  - Returns: `patch_summary`, `vulnerable_packages`, `patched_manifest`, options

### 3. HITL Gate (Governance Rule 11)
- Creates incident with severity summary as raw_log
- `interrupt()` pauses workflow — operator reviews in dashboard
- Dashboard shows: vulnerability count, CRITICAL/HIGH counts, patch summary
- Approves via `POST /incidents/{id}/approve`

### 4. Execute (Post-Approval)
- **opt_1 — Create Patch PR**: Opens a PR with patched manifest. CI validates the version bump.
- **opt_2 — Create Vulnerability Issue**: Documents all CVEs in a GitHub issue for manual tracking.
- **opt_3 — Create Patch PR + Issue**: Both actions.
- **hold**: No action; operator copies the report manually.

### 5. Complete
- Marks incident as executed
- Writes final audit record

---

## Approval Options

| Option | When to Choose |
|---|---|
| **opt_1 — Create Patch PR** | Ready to apply the fix; CI will validate before merge |
| **opt_2 — Create Vulnerability Issue** | Need manual review (complex dependency constraints) or want a ticket first |
| **opt_3 — Create Patch PR + Issue** | Default for CRITICAL/HIGH — patch ready + visible tracking |
| **hold** | False positive, or manual remediation already in progress |

---

## GitHub CI Integration (Scheduled Scan)

```yaml
# .github/workflows/dependency-scan.yml
name: Dependency Security Scan
on:
  schedule:
    - cron: '0 6 * * 1'  # Every Monday at 06:00 UTC
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Cloud Decoded Agent 10
        run: |
          curl -X POST https://your-api.cloud-decoded.com/agents/agent_10_dependency_patch/run \
            -H "Authorization: Bearer ${{ secrets.CLOUD_DECODED_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d '{
              "payload": {
                "repository": "${{ github.repository }}",
                "ecosystem": "pip",
                "manifest_path": "requirements.txt",
                "ref": "main"
              },
              "cloud_provider": "aws"
            }'
```

---

## OSV.dev Scan Limits

- Agent 10 scans up to **40 packages** per run against OSV.dev
- Packages beyond 40 are noted in the report but not scanned
- No API key required for OSV.dev — it is a free, public API
- Rate limit: OSV.dev allows up to 100 queries/minute per IP

For repos with many dependencies (>40), trigger separate scans with different manifest files, or use `Dependabot` / `Snyk` for full-repo coverage alongside Cloud Decoded for CI-integrated automated patching.

---

## Security & Compliance

- **No install commands**: The agent only edits the manifest file — `npm install`, `pip install`, etc. run in your CI pipeline after merge (Governance Rule 11).
- **Audit Trail**: Every node writes to `audit_log` table (Rule 9).
- **LLM Routing**: All LLM calls go through `.llm/router.py` (Rule 6).
- **No Autonomous Merge**: The patch PR requires human review and CI passage before merge (Rule 11).
- **GITHUB_TOKEN required**: Without it, manifest fetch and PR/issue creation are skipped.

---

## Error Handling

| Error | Behavior |
|---|---|
| `GITHUB_TOKEN` missing | Manifest fetch fails; agent reports error, HITL gate skipped |
| Manifest not found (404) | `error` set in state; HITL gate skipped |
| Unknown ecosystem | Dependencies parsed as empty list; LLM proceeds without dependency context |
| OSV API unavailable | Individual packages skipped; scan continues for the rest |
| LLM parse failure | `error` set; HITL gate skipped; no incident created |
| No fixed version available | Package left at current version; noted in `patch_summary` |
| Patched manifest empty | `opt_1` skipped with reason; `opt_2`/`opt_3` still create the tracking issue |
