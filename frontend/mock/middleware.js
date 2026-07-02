/**
 * mock/middleware.js
 * json-server middleware for Cloud Decoded local mock environment.
 *
 * Handles:
 *   - CORS for the Next.js dev server (localhost:3000 → localhost:3001)
 *   - /api/v1 prefix stripping (matches what api.ts sends)
 *   - status_filter → execution_status query param rewrite (json-server native filter)
 *   - POST .../incidents/:id/approve (not a native json-server route)
 *   - POST .../webhooks/github (webhook simulation)
 *   - X-Workspace-Token: test-token-suspended → 403 (compliance gate smoke test)
 */

module.exports = (req, res, next) => {
  // ── CORS ──────────────────────────────────────────────────────────────
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, X-Workspace-Token, Authorization');

  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }

  // ── Suspended workspace smoke test ────────────────────────────────────
  // Use token "test-token-suspended" to verify 403 handling in the frontend.
  const token = req.headers['x-workspace-token'];
  if (token === 'test-token-suspended') {
    return res.status(403).json({
      error: 'Access suspended due to non-payment or terms violation.',
      code: 'WORKSPACE_SUSPENDED'
    });
  }

  // ── Mock: POST .../incidents/:id/approve ──────────────────────────────
  // Must be intercepted before the /api/v1 strip so the regex can match either
  // /api/v1/incidents/:id/approve or /incidents/:id/approve.
  const approveMatch = req.url.match(/\/incidents\/([^/?]+)\/approve/);
  if (req.method === 'POST' && approveMatch) {
    const incidentId = approveMatch[1];
    const body = req.body || {};
    const optionId = body.selected_option_id || '';
    const customText = (body.custom_solution_text || '').toLowerCase();

    // "hold" option or custom text containing "stay broken" → held status
    const isHeld = optionId === 'hold' ||
      (optionId === 'custom' && customText.includes('stay broken'));

    const newStatus = isHeld ? 'held' : 'executing';

    // Write the new status back to the lowdb adapter so subsequent GETs
    // return the updated status rather than reverting on the next poll.
    const db = req.app.db;
    try {
      if (db) {
        db.get('incidents')
          .find(inc => inc.incident_id === incidentId)
          .assign({ status: newStatus })
          .write();
      }
    } catch (_) { /* non-fatal */ }

    // Auto-complete: after ~8s write the final status so the next poll
    // moves the incident to Resolved or Failed. 1-in-4 chance of failure
    // so the failure path is demonstrable without being contrived.
    if (!isHeld && db) {
      const COMPLETE_DELAY_MS = 8000;
      const finalStatus = Math.random() < 0.25 ? 'failed' : 'executed';
      setTimeout(() => {
        try {
          db.get('incidents')
            .find(inc => inc.incident_id === incidentId)
            .assign({ status: finalStatus })
            .write();
        } catch (_) { /* non-fatal */ }
      }, COMPLETE_DELAY_MS);
    }

    return res.json({
      incident_id: incidentId,
      selected_option: optionId,
      status: newStatus,
      message: isHeld
        ? 'Incident held for manual resolution.'
        : 'Remediation executing. Pipeline rerun initiated.',
      estimated_completion_seconds: 45
    });
  }

  // ── Mock: POST .../webhooks/github ────────────────────────────────────
  if (req.method === 'POST' && req.url.includes('/webhooks/github')) {
    return res.json({
      incident_id: 'inc-live-' + Date.now(),
      status: 'pending_approval',
      message: 'Incident created and queued for LLM diagnosis.'
    });
  }

  // ── Strip /api/v1 prefix ──────────────────────────────────────────────
  // api.ts sends requests to ${NEXT_PUBLIC_API_URL}/api/v1/...
  // json-server serves resources at /incidents, /workspaces, etc.
  if (req.url.startsWith('/api/v1')) {
    req.url = req.url.replace('/api/v1', '');
  }

  // ── Rewrite status_filter → status ────────────────────────────────────
  // Frontend sends ?status_filter=pending_approval; json-server filters by
  // field name. db.json uses "status", so rewrite both req.url AND req.query
  // (Express may cache one or the other).
  if (req.query && req.query.status_filter) {
    const val = req.query.status_filter;
    req.query.status = val;
    delete req.query.status_filter;
    req.url = req.url.replace(`status_filter=${val}`, `status=${val}`);
  } else if (req.url.includes('status_filter=')) {
    req.url = req.url.replace('status_filter=', 'status=');
  }

  next();
};
