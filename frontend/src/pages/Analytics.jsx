import { useMemo, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import NotificationsIcon from "@mui/icons-material/NotificationsActive";
import BlockIcon from "@mui/icons-material/Block";
import HandshakeIcon from "@mui/icons-material/Handshake";
import TimerIcon from "@mui/icons-material/Timer";

import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip as ChartTooltip,
} from "chart.js";
import { Bar, Line } from "react-chartjs-2";
import dayjs from "dayjs";

import { analytics, cameras } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { HourHeatmap } from "@insighteye/ui";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { formatDuration, formatNumber, formatScore, titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Filler,
  ChartTooltip,
  Legend
);

const WINDOWS = [
  { value: 1, get label() { return i18n.t("analytics.last24Hours"); } },
  { value: 7, get label() { return i18n.t("analytics.last7Days"); } },
  { value: 30, get label() { return i18n.t("analytics.last30Days"); } },
  { value: 90, get label() { return i18n.t("analytics.last90Days"); } },
];

// The busiest cameras are the story; the long tail stays in the table below.
const CAMERA_CHART_LIMIT = 10;

// Buckets are cut in the viewer's zone, so "busiest hour" means their hour.
const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const formatPct = (value) =>
  value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
const share = (part, whole) => (whole ? (100 * part) / whole : null);

function ChartCard({ title, subtitle, children }) {
  return (
    <Card sx={{ height: "100%" }}>
      <CardContent>
        <Typography variant="subtitle2">{title}</Typography>
        {subtitle && (
          <Typography variant="caption" color="text.secondary">
            {subtitle}
          </Typography>
        )}
        <Box sx={{ mt: 2 }}>{children}</Box>
      </CardContent>
    </Card>
  );
}

/** Detection to reunion, one bar per stage, scaled to the largest stage. */
function Funnel({ stages }) {
  const max = Math.max(1, ...stages.map((stage) => stage.value));
  return (
    <Stack spacing={2.25}>
      {stages.map((stage) => (
        <Box key={stage.key}>
          <Stack direction="row" justifyContent="space-between" alignItems="baseline" spacing={1}>
            <Typography variant="body2">{stage.label}</Typography>
            <Typography variant="body2" fontWeight={600}>
              {formatNumber(stage.value)}
            </Typography>
          </Stack>
          <LinearProgress
            variant="determinate"
            value={(100 * stage.value) / max}
            sx={{ height: 8, borderRadius: 4, my: 0.5 }}
          />
          {stage.caption && (
            <Typography variant="caption" color="text.secondary">
              {stage.caption}
            </Typography>
          )}
        </Box>
      ))}
    </Stack>
  );
}

/**
 * Model accuracy & confidence audit: how sure the detector was about the
 * alerts in the window, with operator verdicts standing in for ground truth.
 */
function ConfidenceAudit({ audit, baseOptions, theme, dismissed }) {
  const { t } = useTranslation();
  const summary = audit.summary;

  const histogram = useMemo(() => {
    const buckets = audit.histogram || [];
    const segment = { borderColor: theme.palette.background.paper, borderWidth: 1, borderRadius: 4 };
    return {
      data: {
        labels: buckets.map((bucket) => `${Math.round(bucket.min * 100)}–${Math.round(bucket.max * 100)}%`),
        datasets: [
          {
            label: t("analytics.alerts"),
            data: buckets.map((bucket) => bucket.count - bucket.false_positives),
            backgroundColor: theme.palette.primary.main,
            ...segment,
          },
          {
            label: t("analytics.falsePositives"),
            data: buckets.map((bucket) => bucket.false_positives),
            backgroundColor: dismissed,
            ...segment,
          },
        ],
      },
      options: {
        ...baseOptions,
        scales: {
          x: { ...baseOptions.scales.x, stacked: true },
          y: { ...baseOptions.scales.y, stacked: true },
        },
        plugins: {
          ...baseOptions.plugins,
          tooltip: {
            callbacks: { title: (items) => (items.length ? `Confidence ${items[0].label}` : "") },
          },
        },
      },
    };
  }, [audit, baseOptions, theme, dismissed, t]);

  if (!summary.scored_events) {
    return (
      <ChartCard title={t("analytics.modelConfidenceAudit")} subtitle={t("analytics.noScoredAlertsInThis")}>
        <Typography variant="body2" color="text.secondary">
          {t("analytics.alertsRecordedWithoutADetector")}
        </Typography>
      </ChartCard>
    );
  }

  const facts = [
    { label: t("analytics.averageConfidence"), value: formatScore(summary.avg_confidence) },
    {
      label: t("analytics.range"),
      value: `${formatScore(summary.min_confidence, 0)} – ${formatScore(summary.max_confidence, 0)}`,
    },
    {
      label: t("analytics.belowV0", { v0: formatScore(summary.low_confidence_cutoff, 0) }),
      value: `${formatNumber(summary.low_confidence)} (${formatPct(summary.low_confidence_pct)})`,
    },
    { label: t("analytics.avgOnResolved"), value: formatScore(summary.avg_confidence_resolved) },
    { label: t("analytics.avgOnFalsePositives"), value: formatScore(summary.avg_confidence_false_positive) },
  ];

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle2">{t("analytics.modelConfidenceAudit")}</Typography>
        <Typography variant="caption" color="text.secondary">
          {t("analytics.detectorConfidenceOfV0Scored", { v0: formatNumber(summary.scored_events) })}
        </Typography>
        <Grid container spacing={3} sx={{ mt: 1 }}>
          <Grid size={{ xs: 12, lg: 8 }}>
            <Box sx={{ height: 260 }}>
              <Bar data={histogram.data} options={histogram.options} />
            </Box>
          </Grid>
          <Grid size={{ xs: 12, lg: 4 }}>
            <Stack spacing={1.25}>
              {facts.map((fact) => (
                <Stack key={fact.label} direction="row" justifyContent="space-between" spacing={2}>
                  <Typography variant="body2" color="text.secondary">
                    {fact.label}
                  </Typography>
                  <Typography variant="body2" fontWeight={600}>
                    {fact.value}
                  </Typography>
                </Stack>
              ))}
              <Typography variant="caption" color="text.disabled">
                {t("analytics.detectorThresholdV0TheTracker", { v0: formatScore(summary.threshold, 0) })}
              </Typography>
            </Stack>
          </Grid>
        </Grid>
      </CardContent>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("analytics.camera")}</TableCell>
              <TableCell align="right">{t("analytics.scoredAlerts")}</TableCell>
              <TableCell align="right">{t("analytics.avg")}</TableCell>
              <TableCell align="right">{t("analytics.minMax")}</TableCell>
              <TableCell align="right">{t("analytics.lowConfidence")}</TableCell>
              <TableCell align="right">{t("analytics.falsePositives")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {audit.by_camera.map((row) => (
              <TableRow key={row.camera_id || "deleted"} hover>
                <TableCell>{row.camera_name || t("analytics.deletedCamera")}</TableCell>
                <TableCell align="right">{formatNumber(row.events)}</TableCell>
                <TableCell align="right">{formatScore(row.avg_confidence)}</TableCell>
                <TableCell align="right">
                  {formatScore(row.min_confidence, 0)} – {formatScore(row.max_confidence, 0)}
                </TableCell>
                <TableCell align="right">{formatNumber(row.low_confidence)}</TableCell>
                <TableCell align="right">
                  {formatNumber(row.false_positives)} ({formatPct(row.false_positive_pct)})
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Card>
  );
}

export default function Analytics() {
  const { t } = useTranslation();
  const theme = useTheme();
  const [days, setDays] = useState(7);
  const [cameraId, setCameraId] = useState("");

  const cameraList = useAsync(({ signal }) => cameras.list(undefined, { signal }), []);

  const { data, error, loading, refresh } = useAsync(
    ({ signal }) =>
      analytics.summary(
        { days, camera_id: cameraId || undefined, tz: TIMEZONE },
        { signal }
      ),
    [days, cameraId]
  );

  // A separate request, so the main charts never wait on the audit.
  const audit = useAsync(
    ({ signal }) =>
      analytics.confidenceAudit(
        { days, camera_id: cameraId || undefined, tz: TIMEZONE },
        { signal }
      ),
    [days, cameraId]
  );

  const summary = data?.data;
  const kpis = summary?.kpis;
  const hourly = summary?.window?.bucket === "hour";
  const hasEvents = Boolean(kpis?.events);

  // Muted grey is what a false positive already wears everywhere else in the
  // console (EVENT_STATUS_COLOR.FALSE_POSITIVE is "default"): it is noise the
  // operator dismissed, not an alarm in its own right.
  const dismissed = theme.palette.grey[500];

  const baseOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          ticks: { color: theme.palette.text.secondary, maxRotation: 0, autoSkipPadding: 12 },
          grid: { display: false },
          border: { color: theme.palette.divider },
        },
        y: {
          beginAtZero: true,
          ticks: { color: theme.palette.text.secondary, precision: 0 },
          grid: { color: theme.palette.divider },
          border: { display: false },
        },
      },
      plugins: {
        legend: {
          position: "top",
          align: "end",
          labels: {
            color: theme.palette.text.secondary,
            boxWidth: 10,
            boxHeight: 10,
            useBorderRadius: true,
            borderRadius: 2,
          },
        },
      },
    }),
    [theme]
  );

  const trend = useMemo(() => {
    const points = summary?.series || [];
    return {
      data: {
        labels: points.map((point) =>
          dayjs(point.bucket_start).format(hourly ? "HH:mm" : "MMM D")
        ),
        datasets: [
          {
            label: t("analytics.alerts"),
            data: points.map((point) => point.events),
            borderColor: theme.palette.primary.main,
            backgroundColor: theme.palette.primary.main + "22",
            fill: true,
            borderWidth: 2,
            // Monotone: smooth, but never overshoots below zero or above a peak.
            cubicInterpolationMode: "monotone",
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBorderWidth: 2,
            pointHoverBorderColor: theme.palette.background.paper,
          },
          {
            label: t("analytics.falsePositives"),
            data: points.map((point) => point.false_positives),
            borderColor: dismissed,
            backgroundColor: dismissed,
            borderWidth: 2,
            cubicInterpolationMode: "monotone",
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBorderWidth: 2,
            pointHoverBorderColor: theme.palette.background.paper,
          },
        ],
      },
      options: {
        ...baseOptions,
        plugins: {
          ...baseOptions.plugins,
          legend: {
            ...baseOptions.plugins.legend,
            labels: {
              ...baseOptions.plugins.legend.labels,
              // The legend swatch would otherwise take the translucent area
              // fill and read as an empty box; show the line colour instead.
              generateLabels: (chart) =>
                ChartJS.defaults.plugins.legend.labels
                  .generateLabels(chart)
                  .map((label) => ({ ...label, fillStyle: label.strokeStyle })),
            },
          },
          tooltip: {
            callbacks: {
              title: (items) =>
                items.length
                  ? dayjs(points[items[0].dataIndex].bucket_start).format(
                      hourly ? "ddd MMM D, HH:00" : "ddd MMM D"
                    )
                  : "",
            },
          },
        },
      },
    };
  }, [summary, hourly, theme, baseOptions, dismissed, t]);

  const byCamera = useMemo(() => {
    const rows = (summary?.by_camera || []).slice(0, CAMERA_CHART_LIMIT);
    // A 1px surface-coloured edge on each segment leaves a 2px gap between them.
    const segment = {
      borderColor: theme.palette.background.paper,
      borderWidth: 1,
      borderSkipped: false,
      borderRadius: 4,
      barThickness: 16,
    };
    return {
      height: Math.max(160, rows.length * 30 + 48),
      data: {
        labels: rows.map((row) => row.camera_name || t("analytics.deletedCamera")),
        datasets: [
          {
            label: t("analytics.alerts"),
            data: rows.map((row) => row.events - row.false_positives),
            backgroundColor: theme.palette.primary.main,
            ...segment,
          },
          {
            label: t("analytics.falsePositives"),
            data: rows.map((row) => row.false_positives),
            backgroundColor: dismissed,
            ...segment,
          },
        ],
      },
      options: {
        ...baseOptions,
        indexAxis: "y",
        interaction: { mode: "index", axis: "y", intersect: false },
        scales: {
          x: { ...baseOptions.scales.y, stacked: true },
          y: { ...baseOptions.scales.x, stacked: true },
        },
      },
    };
  }, [summary, theme, baseOptions, dismissed, t]);

  const byClass = useMemo(() => {
    const rows = summary?.by_class || [];
    return {
      height: Math.max(160, rows.length * 30 + 24),
      data: {
        labels: rows.map((row) => titleCase(row.class_name)),
        datasets: [
          {
            label: t("analytics.alerts"),
            data: rows.map((row) => row.events),
            backgroundColor: theme.palette.primary.main,
            borderRadius: 4,
            barThickness: 16,
          },
        ],
      },
      options: {
        ...baseOptions,
        indexAxis: "y",
        interaction: { mode: "index", axis: "y", intersect: false },
        scales: { x: baseOptions.scales.y, y: baseOptions.scales.x },
        plugins: {
          ...baseOptions.plugins,
          // One series: the card title names it, a legend box would only repeat it.
          legend: { display: false },
          tooltip: {
            callbacks: {
              afterLabel: (item) => {
                const row = rows[item.dataIndex];
                const confidence =
                  row.avg_confidence === null ? "—" : `${(row.avg_confidence * 100).toFixed(0)}%`;
                return t("analytics.cameraTooltip", { confidence, count: row.false_positives });
              },
            },
          },
        },
      },
    };
  }, [summary, theme, baseOptions, t]);

  const funnel = summary?.funnel;
  const funnelStages = funnel
    ? [
        { key: "detected", label: t("analytics.alertsRaised"), value: funnel.events_detected },
        {
          key: "harvested",
          label: t("analytics.addedToFoundGallery"),
          value: funnel.items_harvested,
          caption: funnel.events_detected
            ? `${formatPct(share(funnel.items_harvested, funnel.events_detected))} of alerts`
            : null,
        },
        {
          key: "reports",
          label: t("analytics.lostReportsFiled"),
          value: funnel.reports_filed,
          caption: cameraId ? t("analytics.reportsNotPerCamera") : null,
        },
        {
          key: "reunions",
          label: t("analytics.reunitedWithOwner"),
          value: funnel.reunions,
          caption: funnel.reports_filed
            ? `${formatPct(share(funnel.reunions, funnel.reports_filed))} of reports`
            : null,
        },
      ]
    : [];

  const windowLabel = WINDOWS.find((option) => option.value === days)?.label.toLowerCase();

  return (
    <Box>
      <PageHeader
        title={t("analytics.analytics")}
        subtitle={t("analytics.whatTheCamerasFlaggedWhen", { TIMEZONE })}
        actions={
          <>
            <TextField
              select
              size="small"
              label={t("analytics.camera")}
              value={cameraId}
              onChange={(event) => setCameraId(event.target.value)}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">{t("analytics.allCameras")}</MenuItem>
              {(cameraList.data || []).map((camera) => (
                <MenuItem key={camera.camera_id} value={camera.camera_id}>
                  {camera.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label={t("analytics.window")}
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              sx={{ minWidth: 160 }}
            >
              {WINDOWS.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </TextField>
          </>
        }
      />

      <ErrorState error={error} onRetry={refresh} title={t("analytics.couldNotLoadAnalytics")} />

      {!summary && loading ? (
        <Loading label={t("analytics.aggregating")} height={360} />
      ) : summary ? (
        // A refetch dims the previous numbers instead of blanking the page.
        <Box sx={{ opacity: loading ? 0.55 : 1, transition: "opacity 150ms" }}>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label={t("analytics.alerts")}
                value={formatNumber(kpis.events)}
                hint={t("analytics.v0StillOpen", { v0: formatNumber(kpis.open) })}
                icon={<NotificationsIcon />}
                color="warning"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label={t("analytics.falsePositiveRate")}
                value={formatPct(kpis.false_positive_pct)}
                hint={t("analytics.v0Dismissed", { v0: formatNumber(kpis.false_positives) })}
                icon={<BlockIcon />}
                color="secondary"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label={t("analytics.itemsReunited")}
                value={formatNumber(kpis.reunions)}
                hint={t("analytics.ofV0ReportsFiled", { v0: formatNumber(kpis.lost_reports) })}
                icon={<HandshakeIcon />}
                color="success"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label={t("analytics.medianTimeToReunite")}
                value={formatDuration(kpis.median_reunite_s)}
                hint={
                  kpis.fastest_reunite_s !== null
                    ? t("analytics.fastestV0", { v0: formatDuration(kpis.fastest_reunite_s) })
                    : t("analytics.noReunionsInThisWindow")
                }
                icon={<TimerIcon />}
                color="info"
              />
            </Grid>
          </Grid>

          {!hasEvents ? (
            <Card>
              <EmptyState
                title={t("analytics.noAlertsInTheWindowlabel", { windowLabel })}
                description={t("analytics.nothingWasLeftUnattendedLong")}
              />
            </Card>
          ) : (
            <Grid container spacing={2}>
              <Grid size={12}>
                <ChartCard
                  title={hourly ? t("analytics.alertsPerHour") : t("analytics.alertsPerDay")}
                  subtitle={t("analytics.v0AlertsV1DismissedAs", { v0: formatNumber(kpis.events), v1: formatNumber(kpis.false_positives) })}
                >
                  <Box sx={{ height: 280 }}>
                    <Line data={trend.data} options={trend.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 6 }}>
                <ChartCard
                  title={t("analytics.byCamera")}
                  subtitle={
                    summary.by_camera.length > CAMERA_CHART_LIMIT
                      ? t("analytics.topCameraChartLimitOf", { CAMERA_CHART_LIMIT, length: summary.by_camera.length })
                      : t("analytics.validAlertsAndFalsePositives")
                  }
                >
                  <Box sx={{ height: byCamera.height }}>
                    <Bar data={byCamera.data} options={byCamera.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 6 }}>
                <ChartCard title={t("analytics.byObjectType")} subtitle={t("analytics.alertsPerDetectedClass")}>
                  <Box sx={{ height: byClass.height }}>
                    <Bar data={byClass.data} options={byClass.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 8 }}>
                <ChartCard
                  title={t("analytics.whenItemsAreLeft")}
                  subtitle={t("analytics.alertsByWeekdayAndHour")}
                >
                  <HourHeatmap cells={summary.heatmap} valueKey="events" describe={(n) => t("analytics.alertCount", { count: n })} />
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 4 }}>
                <ChartCard title={t("analytics.reunionFunnel")} subtitle={t("analytics.overTheWindowlabel", { windowLabel })}>
                  <Funnel stages={funnelStages} />
                </ChartCard>
              </Grid>

              <Grid size={12}>
                {audit.data?.data ? (
                  <ConfidenceAudit
                    audit={audit.data.data}
                    baseOptions={baseOptions}
                    theme={theme}
                    dismissed={dismissed}
                  />
                ) : (
                  <ErrorState
                    error={audit.error}
                    onRetry={audit.refresh}
                    title={t("analytics.couldNotLoadTheConfidence")}
                  />
                )}
              </Grid>

              <Grid size={12}>
                <Card>
                  <CardContent sx={{ pb: 0 }}>
                    <Typography variant="subtitle2">{t("analytics.cameraBreakdown")}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {t("analytics.unattendedIsHowLongAn")}
                    </Typography>
                  </CardContent>
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>{t("analytics.camera")}</TableCell>
                          <TableCell>{t("analytics.location")}</TableCell>
                          <TableCell align="right">{t("analytics.alerts")}</TableCell>
                          <TableCell align="right">{t("analytics.open")}</TableCell>
                          <TableCell align="right">{t("analytics.falsePositives")}</TableCell>
                          <TableCell align="right">{t("analytics.avgUnattended")}</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {summary.by_camera.map((row) => (
                          <TableRow key={row.camera_id} hover>
                            <TableCell>
                              <Button
                                size="small"
                                component={RouterLink}
                                to={`/cameras/${row.camera_id}`}
                                sx={{ p: 0, minWidth: 0 }}
                              >
                                {row.camera_name || t("analytics.deletedCamera")}
                              </Button>
                            </TableCell>
                            <TableCell>{row.location || "—"}</TableCell>
                            <TableCell align="right">{formatNumber(row.events)}</TableCell>
                            <TableCell align="right">{formatNumber(row.open)}</TableCell>
                            <TableCell align="right">
                              {formatNumber(row.false_positives)} ({formatPct(row.false_positive_pct)})
                            </TableCell>
                            <TableCell align="right">
                              {formatDuration(row.avg_unattended_s)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Card>
              </Grid>
            </Grid>
          )}
        </Box>
      ) : null}
    </Box>
  );
}
