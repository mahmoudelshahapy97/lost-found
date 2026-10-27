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
import LockIcon from "@mui/icons-material/LockOutlined";
import LockOpenIcon from "@mui/icons-material/LockOpen";
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
import { DEFAULT_MIN_MATCH_SCORE, LOST_STATUS } from "../utils/constants";
import { formatDateTime, formatScore, fromNow, titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";

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
  const { t } = useTranslation();
  return (
    <Card
      data-testid="match-card"
      sx={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <ItemImage
        src={foundItems.cropUrl(match.found_id)}
        alt={t("lostItemDetail.foundClassName", { class_name: match.class_name })}
        height={180}
        fallbackLabel={t("lostItemDetail.noCrop")}
      />
      <CardContent sx={{ flexGrow: 1 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle2">{titleCase(match.class_name)}</Typography>
          <Tooltip title={t("lostItemDetail.rawScoreV0", { v0: Number(match.score).toFixed(4) })}>
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
          {t("lostItemDetail.v0FoundV1", { v0: match.camera_name || "Unknown camera", v1: fromNow(match.found_at) })}
        </Typography>

        <Stack direction="row" spacing={0.5} sx={{ mt: 1.5 }} flexWrap="wrap" useFlexGap>
          {match.same_class ? <Chip size="small" variant="outlined" label={t("lostItemDetail.sameType")} /> : null}
          {match.same_color ? <Chip size="small" variant="outlined" label={t("lostItemDetail.sameColour")} /> : null}
          {match.visual_similarity != null ? (
            <Tooltip title={t("lostItemDetail.howMuchTheReportPhoto")}>
              <Chip
                size="small"
                variant="outlined"
                color={match.visual_similarity >= 0.6 ? "success" : "default"}
                label={t("lostItemDetail.looksV0Alike", { v0: Math.round(match.visual_similarity * 100) })}
              />
            </Tooltip>
          ) : null}
          {match.sightings > 1 ? (
            <Chip size="small" color="info" variant="outlined" label={t("lostItemDetail.seenSightings", { sightings: match.sightings })} />
          ) : null}
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
            {t("lostItemDetail.thisIsIt")}
          </Button>
          <Button
            size="small"
            color="inherit"
            startIcon={<CloseIcon />}
            disabled={busy}
            onClick={() => onReject(match)}
          >
            {t("lostItemDetail.notIt")}
          </Button>
        </CardActions>
      )}
    </Card>
  );
}

export default function LostItemDetail() {
  const { t } = useTranslation();
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
      const result = await matchApi.confirm({ lostId, foundId: match.found_id, score: match.score });
      const emailing =
        result?.data?.reporter_email_queued &&
        item.data?.reporter_email &&
        !item.data.reporter_notified_at;
      toast.success(
        t("lostItemDetail.matchConfirmed") + (emailing ? ` ${t("lostItemDetail.reporterEmailed")}` : "")
      );
      item.refresh();
      // The email goes out after the response; look again for its timestamp.
      if (emailing) setTimeout(() => item.refresh(), 3000);
      ranking.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const [pendingClose, setPendingClose] = useState(false);

  const setReportStatus = async (status) => {
    setPendingClose(false);
    setBusy(true);
    try {
      await lostApi.setStatus(lostId, status);
      toast.success(status === LOST_STATUS.CLOSED ? t("lostItemDetail.reportClosed") : t("lostItemDetail.reportReopened"));
      item.refresh();
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
      toast.info(t("lostItemDetail.suggestionDismissed"));
      ranking.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (item.loading && !item.data) return <Loading label={t("lostItemDetail.loadingReport")} />;
  if (item.error) return <ErrorState error={item.error} onRetry={item.refresh} />;
  if (!item.data) return null;

  const report = item.data;
  const candidates = ranking.data?.matches || [];

  return (
    <Box>
      <Button component={RouterLink} to="/lost-items" startIcon={<ArrowBackIcon />} sx={{ mb: 2 }}>
        {t("lostItemDetail.allReports")}
      </Button>

      <PageHeader
        title={report.description || t("lostItemDetail.photoOnlyReport")}
        subtitle={t("lostItemDetail.reportedV0V1", { v0: fromNow(report.reported_at), v1: report.reporter_name ? ` by ${report.reporter_name}` : "" })}
        actions={[
          <Button
            key="rerun"
            onClick={() => ranking.refresh()}
            startIcon={<SearchIcon />}
            disabled={ranking.loading}
          >
            {ranking.loading ? t("lostItemDetail.searching") : t("lostItemDetail.reRunMatching")}
          </Button>,
          canConfirm && report.status === LOST_STATUS.CLOSED ? (
            <Button
              key="reopen"
              onClick={() => setReportStatus(LOST_STATUS.OPEN)}
              startIcon={<LockOpenIcon />}
              disabled={busy}
            >
              {t("lostItemDetail.reopenReport")}
            </Button>
          ) : null,
          canConfirm && [LOST_STATUS.OPEN, LOST_STATUS.MATCHED].includes(report.status) ? (
            <Button
              key="close"
              color="inherit"
              onClick={() => setPendingClose(true)}
              startIcon={<LockIcon />}
              disabled={busy}
            >
              {t("lostItemDetail.closeReport")}
            </Button>
          ) : null,
        ].filter(Boolean)}
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 4, lg: 3 }}>
          <Card>
            <ItemImage
              // The API returns the photo base64-encoded in the JSON rather than
              // as its own endpoint, so it is inlined as a data URL.
              src={report.photo_base64 ? `data:image/jpeg;base64,${report.photo_base64}` : null}
              alt={report.description || t("lostItemDetail.reportedItem")}
              height={220}
              fit="contain"
              fallbackLabel={t("lostItemDetail.noPhoto")}
            />
            <CardContent>
              <DetailRow label={t("lostItemDetail.status")}>
                <LostStatusChip status={report.status} />
              </DetailRow>
              <DetailRow label={t("lostItemDetail.object")}>
                <Typography variant="body2">
                  {report.class_name ? titleCase(report.class_name) : t("lostItemDetail.unspecified")}
                </Typography>
              </DetailRow>
              <DetailRow label={t("lostItemDetail.colour")}>
                <Typography variant="body2" color="text.secondary">
                  {report.dominant_color ? titleCase(report.dominant_color) : "—"}
                </Typography>
              </DetailRow>
              <DetailRow label={t("lostItemDetail.reporter")}>
                <Typography variant="body2">{report.reporter_name || "—"}</Typography>
                {report.reporter_email ? (
                  <Typography variant="caption" color="text.disabled">
                    {report.reporter_email}
                  </Typography>
                ) : null}
                {report.reporter_notified_at ? (
                  <Typography variant="caption" color="success.main" sx={{ display: "block" }}>
                    {t("lostItemDetail.toldItWasFoundV0", { v0: formatDateTime(report.reporter_notified_at) })}
                  </Typography>
                ) : null}
              </DetailRow>
              <DetailRow label={t("lostItemDetail.lostAfter")}>
                <Typography variant="body2" color="text.secondary">
                  {report.lost_after ? formatDateTime(report.lost_after) : t("lostItemDetail.notNarrowed")}
                </Typography>
              </DetailRow>
              <DetailRow label={t("lostItemDetail.reported")}>
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
              {t("lostItemDetail.candidatesFromTheFoundGallery")}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t("lostItemDetail.unclaimedItemsFoundAfterThe", { v0: formatScore(DEFAULT_MIN_MATCH_SCORE, 0) })}
            </Typography>
          </Card>

          <ErrorState error={ranking.error} onRetry={ranking.refresh} title={t("lostItemDetail.matchingFailed")} />

          {ranking.loading && !ranking.data ? (
            <Loading label={t("lostItemDetail.rankingTheGallery")} />
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
                title={t("lostItemDetail.noLikelyMatchesYet")}
                description={t("lostItemDetail.noUnclaimedItemFoundAfter")}
                icon={<SearchIcon fontSize="inherit" />}
                action={
                  <Button component={RouterLink} to="/search" variant="outlined">
                    {t("lostItemDetail.searchTheGallery")}
                  </Button>
                }
              />
            </Card>
          )}
        </Grid>
      </Grid>

      <ConfirmDialog
        open={Boolean(pendingConfirm)}
        title={t("lostItemDetail.confirmThisMatch")}
        description={t("lostItemDetail.theReportIsMarkedResolved")}
        confirmLabel={t("lostItemDetail.confirmMatch")}
        confirmColor="success"
        busy={busy}
        onConfirm={confirm}
        onClose={() => setPendingConfirm(null)}
      />
      <ConfirmDialog
        open={pendingClose}
        title={t("lostItemDetail.closeThisReport")}
        description={t("lostItemDetail.useThisWhenNobodyWill")}
        confirmLabel={t("lostItemDetail.closeReport")}
        busy={busy}
        onConfirm={() => setReportStatus(LOST_STATUS.CLOSED)}
        onClose={() => setPendingClose(false)}
      />
    </Box>
  );
}
