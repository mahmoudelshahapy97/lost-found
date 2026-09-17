/**
 * Mirrors the enums in app/schemas/ and app/services/abandonment_service.py —
 * keep the two in step. The CHECK constraints in database/schema.sql are the
 * ultimate authority on which values a column will accept.
 */

/** abandoned_event.status */
export const EVENT_STATUS = {
  OPEN: "OPEN",
  ACKNOWLEDGED: "ACKNOWLEDGED",
  RESOLVED: "RESOLVED",
  FALSE_POSITIVE: "FALSE_POSITIVE",
};

/** lost_item.status */
export const LOST_STATUS = {
  OPEN: "OPEN",
  MATCHED: "MATCHED",
  RESOLVED: "RESOLVED",
  CLOSED: "CLOSED",
};

/** found_item.status */
export const FOUND_STATUS = {
  UNCLAIMED: "UNCLAIMED",
  CLAIMED: "CLAIMED",
  DISCARDED: "DISCARDED",
};

/** ObjectStatus — the live per-track state the abandonment tracker reports. */
export const TRACK_STATUS = {
  MOVING: "MOVING",
  ATTENDED: "ATTENDED",
  UNATTENDED: "UNATTENDED",
  ABANDONED: "ABANDONED",
};

/**
 * The COCO classes the detector tracks, set by OBJECT_CLASS_IDS in
 * backend/.env: 24 backpack, 26 handbag, 28 suitcase.
 */
export const OBJECT_CLASSES = ["backpack", "handbag", "suitcase"];

export const EVENT_STATUSES = Object.values(EVENT_STATUS);
export const LOST_STATUSES = Object.values(LOST_STATUS);
export const FOUND_STATUSES = Object.values(FOUND_STATUS);

/** MUI palette keys, so a status colours identically everywhere it appears. */
export const EVENT_STATUS_COLOR = {
  OPEN: "error",
  ACKNOWLEDGED: "warning",
  RESOLVED: "success",
  FALSE_POSITIVE: "default",
};

export const LOST_STATUS_COLOR = {
  OPEN: "warning",
  MATCHED: "info",
  RESOLVED: "success",
  CLOSED: "default",
};

export const FOUND_STATUS_COLOR = {
  UNCLAIMED: "warning",
  CLAIMED: "success",
  DISCARDED: "default",
};

export const TRACK_STATUS_COLOR = {
  MOVING: "default",
  ATTENDED: "info",
  UNATTENDED: "warning",
  ABANDONED: "error",
};

export const POLL_INTERVAL_MS = Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 5000;

/** Default page size, matched to the API's per_page default. */
export const PAGE_SIZE = 20;
export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

/**
 * MATCH_MIN_SIMILARITY in backend/.env. Shown in the UI so a search that
 * returns nothing reads as "nothing cleared the bar" rather than "it broke".
 */
export const DEFAULT_MIN_SIMILARITY = 0.55;
