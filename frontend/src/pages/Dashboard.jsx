import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import Link from "@mui/material/Link";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import AddAPhotoIcon from "@mui/icons-material/AddAPhoto";
import Inventory2Icon from "@mui/icons-material/Inventory2";
import NotificationsIcon from "@mui/icons-material/NotificationsActive";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReportProblemIcon from "@mui/icons-material/ReportProblem";
import VideocamIcon from "@mui/icons-material/Videocam";

import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { EnabledChip, EventStatusChip } from "../components/StatusChips";
import { cameras, events, foundItems, lostItems } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { usePolling } from "../hooks/usePolling";
import { POLL_INTERVAL_MS } from "../utils/constants";
import { formatNumber, fromNow, titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";

export default function Dashboard() {
  const { t } = useTranslation();
  // The alert counters are the one thing worth polling: a new abandonment
  // should surface without anyone reaching for refresh.
  const stats = usePolling(({ signal }) => events.stats(undefined, { signal }), {
    intervalMs: POLL_INTERVAL_MS * 4,
  });
  const recent = usePolling(({ signal }) => events.list({ per_page: 8 }, { signal }), {
    intervalMs: POLL_INTERVAL_MS * 4,
  });

  // These change only when a person does something, so one fetch is enough.
  const cameraList = useAsync(({ signal }) => cameras.list(undefined, { signal }), []);
  const openLost = useAsync(
    ({ signal }) => lostItems.list({ status: "OPEN", per_page: 1 }, { signal }),
    []
  );
  const unclaimed = useAsync(
    ({ signal }) => foundItems.list({ status: "UNCLAIMED", per_page: 1 }, { signal }),
    []
  );

  const eventStats = stats.data?.data || {};
  const allCameras = cameraList.data || [];
  const enabledCount = allCameras.filter((camera) => camera.enabled).length;

  const refreshAll = () => {
    stats.refresh();
    recent.refresh();
    cameraList.refresh();
    openLost.refresh();
    unclaimed.refresh();
  };

  return (
    <Box>
      <PageHeader
        title={t("dashboard.dashboard")}
        subtitle={t("dashboard.whatTheCamerasHaveFlagged")}
        actions={[
          <Button
            key="report"
            component={RouterLink}
            to="/lost-items/new"
            variant="contained"
            startIcon={<AddAPhotoIcon />}
          >
            {t("dashboard.reportLostItem")}
          </Button>,
          <Button key="refresh" onClick={refreshAll} startIcon={<RefreshIcon />}>
            {t("dashboard.refresh")}
          </Button>,
        ]}
      />

      <ErrorState error={stats.error} onRetry={stats.refresh} title={t("dashboard.couldNotLoadTheCounters")} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t("dashboard.openAlerts")}
            value={formatNumber(eventStats.open ?? 0)}
            hint={t("dashboard.abandonedObjectsNobodyHasTriaged")}
            icon={<NotificationsIcon />}
            color="error"
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t("dashboard.alertsLast24h")}
            value={formatNumber(eventStats.last_24h ?? 0)}
            hint={
              eventStats.last_event_at
                ? t("dashboard.mostRecentV0", { v0: fromNow(eventStats.last_event_at) })
                : t("dashboard.nothingYet")
            }
            icon={<NotificationsIcon />}
            color="warning"
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t("dashboard.unclaimedItems")}
            value={formatNumber(unclaimed.data?.total ?? 0)}
            hint={t("dashboard.sittingInTheFoundGallery")}
            icon={<Inventory2Icon />}
            color="info"
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
          <StatCard
            label={t("dashboard.openReports")}
            value={formatNumber(openLost.data?.total ?? 0)}
            hint={t("dashboard.peopleStillWaitingOnA")}
            icon={<ReportProblemIcon />}
            color="secondary"
          />
        </Grid>

        <Grid size={{ xs: 12, lg: 8 }}>
          <Card sx={{ height: "100%" }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ px: 2.5, py: 2 }}
            >
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {t("dashboard.recentAlerts")}
              </Typography>
              <Link component={RouterLink} to="/events" variant="body2">
                {t("dashboard.viewAll")}
              </Link>
            </Stack>
            <Divider />

            {recent.error ? (
              <Box sx={{ p: 2 }}>
                <ErrorState error={recent.error} onRetry={recent.refresh} />
              </Box>
            ) : recent.loading && !recent.data ? (
              <Loading label={t("dashboard.loadingAlerts")} />
            ) : recent.data?.events?.length ? (
              <List disablePadding>
                {recent.data.events.map((event) => (
                  <ListItemButton
                    key={event.event_id}
                    component={RouterLink}
                    to={`/events/${event.event_id}`}
                    divider
                  >
                    <ListItemText
                      primary={
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {titleCase(event.class_name)}
                          </Typography>
                          <EventStatusChip status={event.status} />
                        </Stack>
                      }
                      secondary={`${event.camera_name || t("dashboard.unknownCamera")} · ${fromNow(
                        event.abandoned_at
                      )}`}
                    />
                  </ListItemButton>
                ))}
              </List>
            ) : (
              <EmptyState
                title={t("dashboard.noAlertsYet")}
                description={t("dashboard.anAlertAppearsHereAs")}
              />
            )}
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 4 }}>
          <Card sx={{ height: "100%" }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ px: 2.5, py: 2 }}
            >
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {t("dashboard.cameras")}
              </Typography>
              <Link component={RouterLink} to="/cameras" variant="body2">
                {t("dashboard.manage")}
              </Link>
            </Stack>
            <Divider />

            <CardContent sx={{ py: 2 }}>
              <Typography variant="h4">
                {enabledCount}
                <Typography component="span" variant="h6" color="text.disabled">
                  {` / ${allCameras.length}`}
                </Typography>
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {t("dashboard.enabled")}
              </Typography>
            </CardContent>
            <Divider />

            {cameraList.loading && !cameraList.data ? (
              <Loading label={t("dashboard.loadingCameras")} height={140} />
            ) : allCameras.length ? (
              <List disablePadding>
                {allCameras.slice(0, 6).map((camera) => (
                  <ListItemButton
                    key={camera.camera_id}
                    component={RouterLink}
                    to={`/cameras/${camera.camera_id}`}
                    divider
                  >
                    <ListItemText
                      primary={camera.name}
                      secondary={camera.location || t("dashboard.noLocationSet")}
                      primaryTypographyProps={{ variant: "body2", fontWeight: 600 }}
                    />
                    <EnabledChip enabled={camera.enabled} />
                  </ListItemButton>
                ))}
              </List>
            ) : (
              <EmptyState
                title={t("dashboard.noCameras")}
                description={t("dashboard.registerAnRtspSourceTo")}
                icon={<VideocamIcon fontSize="inherit" />}
                action={
                  <Button
                    component={RouterLink}
                    to="/cameras/new"
                    variant="contained"
                    size="small"
                  >
                    {t("dashboard.addACamera")}
                  </Button>
                }
              />
            )}
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
