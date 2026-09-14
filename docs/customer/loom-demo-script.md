# Cloud Decoded — Loom Demo Script (v1)

**Scenario:** CI/CD failure triage (Agent 01) — the first proof-of-concept
scenario per the build order. Record after a real demo workspace with a
connected GitHub repo is stood up; this is a screen-recording script, not
a written explainer.

**Length target:** 2:00. **Tone:** calm, specific, no narrator voice-over
energy — talk like you're showing a colleague something that actually
works, not pitching.

---

## 0:00–0:15 — Hook

**Screen:** A Slack/PagerDuty notification, timestamped 2:14am, for a
failed deploy.

**Voice:**
> "It's 2am. Your deploy just failed. Normally someone's getting paged
> to go dig through logs and figure out why. Here's what happens
> instead with Cloud Decoded."

Cut fast — this section earns the next 100 seconds, don't linger.

## 0:15–1:30 — Solution in action

**Beat 1 (0:15–0:35): the failure, live**
- Screen: a real GitHub Actions run, red X, the failed step visible.
- Trigger it live if possible (a genuinely broken build in the demo
  repo) rather than a pre-recorded failure — it reads as more real.
- Voice: "This is a real pipeline in a real repo. It just failed."

**Beat 2 (0:35–1:00): the triage card lands**
- Screen: cut to the Cloud Decoded dashboard, HITL queue. The triage
  card appears (or is already there if timing live triggering is
  risky) — show the parsed root cause and the proposed fix, not just a
  loading spinner.
- Voice: "Within moments, Cloud Decoded already knows what broke —
  [read the actual root cause it found] — and it's proposing a fix. Not
  guessing. This is a diff against the actual failing config."

**Beat 3 (1:00–1:20): the approval**
- Screen: click into the option, show the diff/plan clearly, then
  click Approve.
- Voice: "Nothing happens until I say so. I can see exactly what it
  wants to do before it does it. I approve — and now it runs."

**Beat 4 (1:20–1:30): the result**
- Screen: the workflow re-running (or the new PR), green check.
- Voice: "Fixed. No page. No context-switching. The person who'd have
  spent twenty minutes on this got twenty minutes back."

## 1:30–2:00 — Outcome + CTA

**Voice:**
> "That's one of ten agents — this one for CI/CD. Same pattern for
> Kubernetes alerts, IAM cleanup, cost waste, dependency patching. It
> connects to what you already run — GitHub or Azure DevOps, AWS or
> Azure, your existing cluster. No migration. And nothing executes
> without a human approving it, every time, no exceptions."

**Screen:** Cut to the Cloud Decoded homepage / pricing, CTA visible.

> "Start a free trial at theclouddecoded.com — you'll see a real
> proposal against your own infrastructure, not a demo environment,
> inside the first day."

**End card:** logo + `theclouddecoded.com` + "Start free trial."

---

## Production notes

- Record the real failure live if the demo repo is stable enough to
  break/fix repeatedly without flaking — a real, unscripted failure is
  much more convincing than a staged one, and this product's whole
  pitch is "this actually happens."
- Keep the HITL approval moment unhurried — it's the entire
  differentiation claim (no autonomous execution). Don't rush past it.
- Nothing above the fold on the landing page should autoplay this —
  per the design brief, motion on the page itself is data-transition
  only; this video is a separate asset, embedded, user-initiated.
