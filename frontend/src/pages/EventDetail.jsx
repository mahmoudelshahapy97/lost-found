import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutline";
import DoneAllIcon from "@mui/icons-material/DoneAll";
import ThumbDownOffAltIcon from "@mui/icons-material/ThumbDownOffAlt";

import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { ErrorState, Loading } from "../components/DataStates";
import { EventStatusChip } from "../components/StatusChips";
import { useToast } from "../components/Toast";
import { errorMessage } from "../api/client";
import { events as eventApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { EVENT_STATUS } from "../utils/constants";
import { describeBox, formatDateTime, formatScore, fromNow, shortId, titleCase } from "../utils/format";

function DetailRow({ label, children }) {
  return (
    <Stack direction="row" spacing={2} sx={{ py: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 150, flexShrink: 0 }}>
        {label}
      </Typography>
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
    </Stack>
  );
}

/** The three ways an operator closes out an alert. */
const TRIAGE = [
  {
    status: EVENT_STATUS.ACKNOWLEDGED,
    label: "Acknowledge",
    icon: <CheckCircleOutlineIcon />,
    color: "warning",
  },
  { status: EVENT_STATUS.RESOLVED, label: "Resolve", icon: <DoneAllIcon />, color: "success" },
  {
    status: EVENT_STATUS.FALSE_POSITIVE,
    label: "False positive",
    icon: <ThumbDownOffAltIcon />,
    color: "inherit",
  },
];

export default function EventDetail() {
  const { eventId } = useParams();
  const toast = useToast();
  const { hasRole } = useAuth();
  const canTriage = hasRole("operator");
  const [busy, setBusy] = useState(false);

  // include_frame=false: the annotated frame is fetched as an image instead, so
  // it streams and caches rather than riding along base64-inflated in the JSON.
  const { data, error, loading, refresh } = useAsync(
    ({ signal }) => eventApi.get(eventId, { include_frame: false }, { signal }),
    [eventId]
  );

  const setStatus = async (status) => {
    setBusy(true);
    try {
      await eventApi.setStatus(eventId, status);
      toast.success(`Alert marked ${titleCase(status).toLowerCase()}.`);
      refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) return <Loading label="Loading alert…" />;
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (!data) return null;

  return (
    <Box>
      <Button component={RouterLink} to="/events" startIcon={<ArrowBackIcon />} sx={{ mb: 2 }}>
        All alerts
      </Button>

      <PageHeader
        title={`Abandoned ${data.class_name}`}
        subtitle={`${data.camera_name || "Unknown camera"} · ${fromNow(data.abandoned_at)}`}
        actions={
          canTriage &&
          TRIAGE.map(({ status, label, icon, color }) => (
            <Button
              key={status}
              variant={data.status === status ? "contained" : "outlined"}
              color={color}
              startIcon={icon}
              disabled={busy || data.status === status}
              onClick={() => setStatus(status)}
            >
              {label}
            </Button>
          ))
        }
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card>
            <Box sx={{ px: 2.5, py: 1.5 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                Alert frame
              </Typography>
              <Typography variant="caption" color="text.secondary">
                The annotated frame captured the moment the object was declared abandoned.
              </Typography>
            </Box>
            <Divider />
            <ItemImage
              src={eventApi.frameUrl(eventId)}
              alt={`Annotated frame for the abandoned ${data.class_name}`}
              height={420}
              fit="contain"
              fallbackLabel="No frame stored for this alert"
            />
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                Detection
              </Typography>
              <Divider />
              <DetailRow label="Status">
                <EventStatusChip status={data.status} />
              </DetailRow>
              <DetailRow label="Object">
                <Typography variant="body2">{titleCase(data.class_name)}</Typography>
              </DetailRow>
              <DetailRow label="Confidence">
                <Typography variant="body2">{formatScore(data.confidence)}</Typography>
              </DetailRow>
              <DetailRow label="Dominant colour">
                <Typography variant="body2">
                  {data.dominant_color ? titleCase(data.dominant_color) : "Not extracted"}
                </Typography>
              </DetailRow>
              <DetailRow label="Bounding box">
                <Typography variant="body2" color="text.secondary">
                  {describeBox(data.bbox)}
                </Typography>
              </DetailRow>
              <DetailRow label="Owner track">
                <Typography variant="body2" color="text.secondary">
                  {data.owner_track_id !== null && data.owner_track_id !== undefined
                    ? `#${data.owner_track_id} walked away`
                    : "No owner was ever associated"}
                </Typography>
              </DetailRow>
            </CardContent>
          </Card>

          <Card sx={{ mt: 2 }}>
            <CardContent>
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                Timeline
              </Typography>
              <Divider />
              <DetailRow label="First seen">
                <Typography variant="body2" color="text.secondary">
                  {formatDateTime(data.first_seen_at)}
                </Typography>
              </DetailRow>
              <DetailRow label="Went static">
                <Typography variant="body2" color="text.secondary">
                  {formatDateTime(data.static_since)}
                </Typography>
              </DetailRow>
              <DetailRow label="Declared abandoned">
                <Typography variant="body2">{formatDateTime(data.abandoned_at)}</Typography>
              </DetailRow>
              <DetailRow label="Identity">
                <Typography variant="caption" color="text.disabled">
                  {data.track_key ? `track #${data.track_key}` : "no track"} · event{" "}
                  {shortId(data.event_id)}
                </Typography>
              </DetailRow>
            </CardContent>
          </Card>

          {data.found_id ? (
            <Card sx={{ mt: 2 }}>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                  Found gallery
                </Typography>
                <Divider sx={{ mb: 2 }} />
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  This object was cropped and embedded into the searchable gallery, so a lost report
                  can be matched against it.
                </Typography>
                <Link component={RouterLink} to="/found-items" variant="body2">
                  Open the found gallery
                </Link>
              </CardContent>
            </Card>
          ) : null}
        </Grid>
      </Grid>
    </Box>
  );
}
