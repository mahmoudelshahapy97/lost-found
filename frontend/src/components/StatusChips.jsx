import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import {
  EVENT_STATUS_COLOR,
  FOUND_STATUS_COLOR,
  LOST_STATUS_COLOR,
  TRACK_STATUS_COLOR,
} from "../utils/constants";
import { titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

const EVENT_HINT = {
  get OPEN() { return i18n.t("statusChips.nobodyHasTriagedThisYet"); },
  get ACKNOWLEDGED() { return i18n.t("statusChips.someoneIsDealingWithIt"); },
  get RESOLVED() { return i18n.t("statusChips.theObjectWasCollectedOr"); },
  get FALSE_POSITIVE() { return i18n.t("statusChips.nothingWasActuallyAbandoned"); },
};

const LOST_HINT = {
  get OPEN() { return i18n.t("statusChips.stillSearchingForAMatch"); },
  get MATCHED() { return i18n.t("statusChips.aCandidateHasBeenShortlisted"); },
  get RESOLVED() { return i18n.t("statusChips.returnedToItsOwner"); },
  get CLOSED() { return i18n.t("statusChips.givenUpOnOrWithdrawn"); },
};

const FOUND_HINT = {
  get UNCLAIMED() { return i18n.t("statusChips.inTheGallerySearchableAgainst"); },
  get CLAIMED() { return i18n.t("statusChips.handedBackNoLongerA"); },
  get DISCARDED() { return i18n.t("statusChips.removedFromTheGallery"); },
};

const TRACK_HINT = {
  get MOVING() { return i18n.t("statusChips.inMotionNotACandidate"); },
  get ATTENDED() { return i18n.t("statusChips.stationaryWithItsOwnerNearby"); },
  get UNATTENDED() { return i18n.t("statusChips.stationaryAndTheOwnerHas"); },
  get ABANDONED() { return i18n.t("statusChips.theUnattendedTimerElapsedAnd"); },
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
  const { t } = useTranslation();
  return (
    <Chip
      label={enabled ? t("statusChips.enabled") : t("statusChips.disabled")}
      color={enabled ? "success" : "default"}
      size={size}
      variant={enabled ? "filled" : "outlined"}
      {...props}
    />
  );
}

/** Whether a worker exists for this camera right now, and whether it has a stream. */
export function WorkerChip({ worker, size = "small", ...props }) {
  const { t } = useTranslation();
  if (!worker || !worker.running) {
    return <Chip label={t("statusChips.stopped")} size={size} variant="outlined" {...props} />;
  }
  return (
    <Tooltip
      title={
        worker.connected
          ? t("statusChips.v0FramesProcessed", { v0: worker.frames_processed ?? 0 })
          : t("statusChips.workerIsUpButThe")
      }
    >
      <Chip
        label={worker.connected ? t("statusChips.streaming") : t("statusChips.reconnecting")}
        color={worker.connected ? "success" : "warning"}
        size={size}
        variant="outlined"
        {...props}
      />
    </Tooltip>
  );
}
