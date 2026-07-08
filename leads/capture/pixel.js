/**
 * PROPRIETARY AND CONFIDENTIAL
 * Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
 *
 * This software is licensed, not sold. Unauthorized copying, modification,
 * distribution, reverse engineering, or prompt extraction is strictly
 * prohibited. Access is governed by the End User License Agreement at
 * /legal/LICENSE.md. Subscription compliance is enforced at runtime —
 * access revokes automatically on non-payment or terms violation.
 */

/**
 * pixel.js — self-hosted, cookie-free anonymous visitor tracking.
 *
 * No third-party pixel, no cookies. Captures only session-scoped,
 * country-level data as described in CLAUDE.md's Lead Capture section:
 * session_id, referrer, UTM params, pages_viewed, time_on_site, and a
 * converted flag. Country is resolved server-side from IP by the
 * receiving endpoint — this script never touches PII.
 *
 * Usage:
 *   <script src="/pixel.js" data-product-id="cloud-decoded"
 *           data-endpoint="/api/track/visitor" defer></script>
 *
 * A page that converts a visitor calls:
 *   window.KDPixel.markConverted();
 */
(function () {
  "use strict";

  var scriptTag = document.currentScript;
  var productId = (scriptTag && scriptTag.dataset.productId) || "unknown";
  var endpoint = (scriptTag && scriptTag.dataset.endpoint) || "/api/track/visitor";

  var STORAGE_PREFIX = "_kd_pixel_";
  var SESSION_ID_KEY = STORAGE_PREFIX + "session_id";
  var SESSION_START_KEY = STORAGE_PREFIX + "session_start";
  var PAGES_VIEWED_KEY = STORAGE_PREFIX + "pages_viewed";

  function generateSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "sid-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function getOrCreateSessionId() {
    var existing = sessionStorage.getItem(SESSION_ID_KEY);
    if (existing) return existing;
    var created = generateSessionId();
    sessionStorage.setItem(SESSION_ID_KEY, created);
    sessionStorage.setItem(SESSION_START_KEY, String(Date.now()));
    sessionStorage.setItem(PAGES_VIEWED_KEY, "0");
    return created;
  }

  function incrementPagesViewed() {
    var count = parseInt(sessionStorage.getItem(PAGES_VIEWED_KEY) || "0", 10) + 1;
    sessionStorage.setItem(PAGES_VIEWED_KEY, String(count));
    return count;
  }

  function getUtmParams() {
    var params = new URLSearchParams(window.location.search);
    return {
      utm_source: params.get("utm_source") || null,
      utm_medium: params.get("utm_medium") || null,
      utm_campaign: params.get("utm_campaign") || null,
    };
  }

  function getTimeOnSiteSeconds() {
    var start = parseInt(sessionStorage.getItem(SESSION_START_KEY) || String(Date.now()), 10);
    return Math.round((Date.now() - start) / 1000);
  }

  function buildEventPayload(extra) {
    var utm = getUtmParams();
    var payload = {
      product_id: productId,
      session_id: getOrCreateSessionId(),
      referrer: document.referrer || null,
      utm_source: utm.utm_source,
      utm_medium: utm.utm_medium,
      utm_campaign: utm.utm_campaign,
      page_path: window.location.pathname,
      pages_viewed: parseInt(sessionStorage.getItem(PAGES_VIEWED_KEY) || "0", 10),
      time_on_site_seconds: getTimeOnSiteSeconds(),
      converted_to_lead: false,
    };
    for (var key in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, key)) payload[key] = extra[key];
    }
    return payload;
  }

  function send(payload) {
    var body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      var blob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(endpoint, blob);
      return;
    }
    // Fallback for browsers without sendBeacon (or when called too late in unload).
    try {
      fetch(endpoint, { method: "POST", body: body, headers: { "Content-Type": "application/json" }, keepalive: true });
    } catch (e) {
      /* best-effort — a dropped tracking event is not user-facing and never blocks the page */
    }
  }

  function trackPageview() {
    incrementPagesViewed();
    send(buildEventPayload({}));
  }

  function trackSessionEnd() {
    send(buildEventPayload({}));
  }

  function markConverted() {
    send(buildEventPayload({ converted_to_lead: true }));
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") trackSessionEnd();
  });
  window.addEventListener("pagehide", trackSessionEnd);

  trackPageview();

  window.KDPixel = { markConverted: markConverted };
})();
