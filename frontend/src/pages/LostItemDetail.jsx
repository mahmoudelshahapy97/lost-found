import { useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActions from "@mui/material/CardActions";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CheckIcon from "@mui/icons-material/Check";
import CloseIcon from "@mui/icons-material/Close";
import SearchIcon from "@mui/icons-material/Search";

import ConfirmDialog from "../components/ConfirmDialog";
import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { FoundStatusChip, LostStatusChip } from "../components/StatusChips";
import { useToast } from "../components/Toast";
import { errorMessage } from "../api/client";
import { foundItems, lostItems as lostApi, matches as matchApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { DEFAULT_MIN_SIMILARITY } from "../utils/constants";
import { formatDateTime, formatScore, fromNow, titleCase } from "../utils/format";

function DetailRow({ label, children }) {
  return (
    <Stack direction="row" spacing={2} sx={{ py: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 130, flexShrink: 0 }}>
        {label}
      </Typography>
      <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
    </Stack>
  );
}

/**
 * One candidate from the gallery. The score breakdown is shown rather than just
 * the total, because "0.81" tells an operator nothing about whether the match
 * came from the picture or from the words.
 */
function MatchCard({ match, onConfirm, onReject, busy, canConfirm }) {
  return (
    <Card
      data-testid="match-card"
      sx={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <ItemImage
        src={foundItems.cropUrl(match.found_id)}
        alt={`Found ${match.class_name}`}
        height={180}
        fallbackLabel="No crop stored"
      />
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle2">{titleCase(match.class_name)}</Typography>
          <Tooltip title={`Raw score ${Number(match.score).toFixed(4)}`}>
            <Chip
              size="small"
              color={match.score >= 0.8 ? "success" : match.score >= 0.65 ? "warning" : "default"}
              label={formatScore(match.score)}
            />
          </Tooltip>
        </Stack>

        <LinearProgress
          variant="determinate"
          value={Math.min(100, Number(match.score) * 100)}
          color={match.score >= 0.8 ? "success" : match.score >= 0.65 ? "warning" : "inherit"}
          sx={{ mb: 1.5, height: 6, borderRadius: 3 }}
        />

        <Typography variant="caption" color="text.secondary" display="block">
          Image similarity {formatScore(match.image_similarity)}
          {match.text_similarity !== null && match.text_similarity !== undefined
            ? ` · text ${formatScore(match.text_similarity)}`
            : ""}
        </Typography>
        <Typography variant="caption" color="text.secondary" display="block">
          {match.camera_name || "Unknown camera"} · found {fromNow(match.found_at)}
        </Typography>

        <Stack direction="row" spacing={0.5} sx={{ mt: 1.5 }} flexWrap="wrap" useFlexGap>
          {match.same_class ? <Chip size="small" variant="outlined" label="Same class" /> : null}
          {match.same_color ? <Chip size="small" variant="outlined" label="Same colour" /> : null}
          {match.dominant_color ? (
            <Chip size="small" variant="outlined" label={titleCase(match.dominant_color)} />
          ) : null}
          <FoundStatusChip status={match.status} />
        </Stack>
      </CardContent>

      {canConfirm && (
        <CardActions sx={{ px: 2, pb: 2 }}>
          <Button
            size="small"
            variant="contained"
            color="success"
            startIcon={<CheckIcon />}
            disabled={busy}
            onClick={() => onConfirm(match)}
          >
            This is it
          </Button>
          <Button
            size="small"
            color="inherit"
            startIcon={<CloseIcon />}
            disabled={busy}
            onClick={() => onReject(match)}
          >
            Not it
          </Button>
        </CardActions>
      )}
    </Card>
  );
}

export default function LostItemDetail() {
  const { lostId } = useParams();
  const toast = useToast();
  const { hasRole } = useAuth();
  const canConfirm = hasRole("operator");

  const item = useAsync(
    ({ signal }) => lostApi.get(lostId, { include_photo: true }, { signal }),
    [lostId]
  );

  // persist=true stores the shortlist, which is what makes it reviewable later
  // from the database rather than only in this tab.
  const ranking = useAsync(
    ({ signal }) => lostApi.matches(lostId, { persist: true }, { signal }),
    [lostId]
  );

  const [busy, setBusy] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState(null);

  const confirm = async () => {
    const match = pendingConfirm;
    setPendingConfirm(null);
    setBusy(true);
    try {
      await matchApi.confirm({ lostId, foundId: match.found_id, score: match.score });
      toast.success("Match confirmed. The report is resolved and the item is marked claimed.");
      item.refresh();
      ranking.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const reject = async (match) => {
    setBusy(true);
    try {
      await matchApi.reject({ lostId, foundId: match.found_id });
      toast.info("Suggestion dismissed.");
      ranking.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (item.loading && !item.data) return <Loading label="Loading report…" />;
  if (item.error) return <ErrorState error={item.error} onRetry={item.refresh} />;
  if (!item.data) return null;

  const report = item.data;
  const candidates = ranking.data?.matches || [];

  return (
    <Box>
      <Button component={RouterLink} to="/lost-items" startIcon={<ArrowBackIcon />} sx={{ mb: 2 }}>
        All reports
      </Button>

      <PageHeader
        title={report.description || "Photo-only report"}
        subtitle={`Reported ${fromNow(report.reported_at)}${
          report.reporter_name ? ` by ${report.reporter_name}` : ""
        }`}
        actions={[
          <Button
            key="rerun"
            onClick={() => ranking.refresh()}
            startIcon={<SearchIcon />}
            disabled={ranking.loading}
          >
            {ranking.loading ? "Searching…" : "Re-run matching"}
          </Button>,
        ]}
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 4, lg: 3 }}>
          <Card>
            <ItemImage
              // The API returns the photo base64-encoded in the JSON rather than
              // as its own endpoint, so it is inlined as a data URL.
              src={report.photo_base64 ? `data:image/jpeg;base64,${report.photo_base64}` : null}
              alt={report.description || "Reported item"}
              height={220}
              fit="contain"
              fallbackLabel="No photo — description only"
            />
            <CardContent>
              <DetailRow label="Status">
                <LostStatusChip status={report.status} />
              </DetailRow>
              <DetailRow label="Object">
                <Typography variant="body2">
                  {report.class_name ? titleCase(report.class_name) : "Unspecified"}
                </Typography>
              </DetailRow>
              <DetailRow label="Colour">
                <Typography variant="body2" color="text.secondary">
                  {report.dominant_color ? titleCase(report.dominant_color) : "—"}
                </Typography>
              </DetailRow>
              <DetailRow label="Reporter">
                <Typography variant="body2">{report.reporter_name || "—"}</Typography>
                {report.reporter_email ? (
                  <Typography variant="caption" color="text.disabled">
                    {report.reporter_email}
                  </Typography>
                ) : null}
              </DetailRow>
              <DetailRow label="Lost after">
                <Typography variant="body2" color="text.secondary">
                  {report.lost_after ? formatDateTime(report.lost_after) : "Not narrowed"}
                </Typography>
              </DetailRow>
              <DetailRow label="Reported">
                <Typography variant="body2" color="text.secondary">
                  {formatDateTime(report.reported_at)}
                </Typography>
              </DetailRow>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 8, lg: 9 }}>
          <Card sx={{ mb: 2, px: 2.5, py: 2 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
              Candidates from the found gallery
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Unclaimed items ranked by cosine similarity in CLIP space, then reranked with small
              bonuses for a matching class and colour. Anything scoring below{" "}
              {formatScore(DEFAULT_MIN_SIMILARITY)} is not shown.
            </Typography>
          </Card>

          <ErrorState error={ranking.error} onRetry={ranking.refresh} title="Matching failed" />

          {ranking.loading && !ranking.data ? (
            <Loading label="Ranking the gallery…" />
          ) : candidates.length ? (
            <Grid container spacing={2}>
              {candidates.map((match) => (
                <Grid key={match.found_id} size={{ xs: 12, sm: 6, lg: 4 }}>
                  <MatchCard
                    match={match}
                    busy={busy}
                    canConfirm={canConfirm}
                    onConfirm={setPendingConfirm}
                    onReject={reject}
                  />
                </Grid>
              ))}
            </Grid>
          ) : (
            <Card>
              <EmptyState
                title="Nothing cleared the similarity bar"
                description="Either the item has not been found yet, or no unclaimed crop in the gallery is close enough. Re-run this once new items come in — the gallery grows as cameras raise alerts."
                icon={<SearchIcon fontSize="inherit" />}
                action={
                  <Button component={RouterLink} to="/found-items" variant="outlined">
                    Browse the whole gallery
                  </Button>
                }
              />
            </Card>
          )}
        </Grid>
      </Grid>

      <ConfirmDialog
        open={Boolean(pendingConfirm)}
        title="Confirm this match?"
        description="The report is marked resolved, the found item is marked claimed, and the alert it came from is closed. The item then drops out of future searches."
        confirmLabel="Confirm match"
        confirmColor="success"
        busy={busy}
        onConfirm={confirm}
        onClose={() => setPendingConfirm(null)}
      />
    </Box>
  );
}
