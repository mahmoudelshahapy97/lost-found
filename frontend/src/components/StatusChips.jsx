import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import {
  EVENT_STATUS_COLOR,
  FOUND_STATUS_COLOR,
  LOST_STATUS_COLOR,
  TRACK_STATUS_COLOR,
} from "../utils/constants";
import { titleCase } from "../utils/format";

const EVENT_HINT = {
  OPEN: "Nobody has triaged this yet",
  ACKNOWLEDGED: "Someone is dealing with it",
  RESOLVED: "The object was collected or removed",
  FALSE_POSITIVE: "Nothing was actually abandoned",
};

const LOST_HINT = {
  OPEN: "Still searching for a match",
  MATCHED: "A candidate has been shortlisted",
  RESOLVED: "Returned to its owner",
  CLOSED: "Given up on, or withdrawn",
};

const FOUND_HINT = {
  UNCLAIMED: "In the gallery, searchable against lost reports",
  CLAIMED: "Handed back — no longer a match candidate",
  DISCARDED: "Removed from the gallery",
};

const TRACK_HINT = {
  MOVING: "In motion — not a candidate for abandonment",
  ATTENDED: "Stationary, with its owner nearby",
  UNATTENDED: "Stationary and the owner has left; the timer is running",
  ABANDONED: "The unattended timer elapsed and an alert was raised",
};

function BaseChip({ value, colors, hints, size, ...props }) {
  if (!value) return null;
  return (
    <Tooltip title={hints[value] || ""}>
      <Chip
        label={titleCase(value)}
        color={colors[value] || "default"}
        size={size}
        variant={colors[value] === "default" ? "outlined" : "filled"}
        {...props}
      />
    </Tooltip>
  );
}

export function EventStatusChip({ status, size = "small", ...props }) {
  return (
    <BaseChip
      value={status}
      colors={EVENT_STATUS_COLOR}
      hints={EVENT_HINT}
      size={size}
      {...props}
    />
  );
}

export function LostStatusChip({ status, size = "small", ...props }) {
  return (
    <BaseChip value={status} colors={LOST_STATUS_COLOR} hints={LOST_HINT} size={size} {...props} />
  );
}

export function FoundStatusChip({ status, size = "small", ...props }) {
  return (
    <BaseChip
      value={status}
      colors={FOUND_STATUS_COLOR}
      hints={FOUND_HINT}
      size={size}
      {...props}
    />
  );
}

export function TrackStatusChip({ status, size = "small", ...props }) {
  return (
    <BaseChip
      value={status}
      colors={TRACK_STATUS_COLOR}
      hints={TRACK_HINT}
      size={size}
      {...props}
    />
  );
}

/** Whether a camera is configured to run, which is not whether it *is* running. */
export function EnabledChip({ enabled, size = "small", ...props }) {
  return (
    <Chip
      label={enabled ? "Enabled" : "Disabled"}
      color={enabled ? "success" : "default"}
      size={size}
      variant={enabled ? "filled" : "outlined"}
      {...props}
    />
  );
}

/** Whether a worker exists for this camera right now, and whether it has a stream. */
export function WorkerChip({ worker, size = "small", ...props }) {
  if (!worker || !worker.running) {
    return <Chip label="Stopped" size={size} variant="outlined" {...props} />;
  }
  return (
    <Tooltip
      title={
        worker.connected
          ? `${worker.frames_processed ?? 0} frames processed`
          : "Worker is up but the RTSP source is not answering"
      }
    >
      <Chip
        label={worker.connected ? "Streaming" : "Reconnecting"}
        color={worker.connected ? "success" : "warning"}
        size={size}
        variant="outlined"
        {...props}
      />
    </Tooltip>
  );
}
