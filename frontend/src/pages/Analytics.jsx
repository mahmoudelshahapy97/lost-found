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
import HourHeatmap from "../components/HourHeatmap";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { formatDuration, formatNumber, formatScore, titleCase } from "../utils/format";

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
  { value: 1, label: "Last 24 hours" },
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
  { value: 90, label: "Last 90 days" },
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
  const summary = audit.summary;

  const histogram = useMemo(() => {
    const buckets = audit.histogram || [];
    const segment = { borderColor: theme.palette.background.paper, borderWidth: 1, borderRadius: 4 };
    return {
      data: {
        labels: buckets.map((bucket) => `${Math.round(bucket.min * 100)}–${Math.round(bucket.max * 100)}%`),
        datasets: [
          {
            label: "Alerts",
            data: buckets.map((bucket) => bucket.count - bucket.false_positives),
            backgroundColor: theme.palette.primary.main,
            ...segment,
          },
          {
            label: "False positives",
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
  }, [audit, baseOptions, theme, dismissed]);

  if (!summary.scored_events) {
    return (
      <ChartCard title="Model confidence audit" subtitle="No scored alerts in this window">
        <Typography variant="body2" color="text.secondary">
          Alerts recorded without a detector confidence are left out of the audit.
        </Typography>
      </ChartCard>
    );
  }

  const facts = [
    { label: "Average confidence", value: formatScore(summary.avg_confidence) },
    {
      label: "Range",
      value: `${formatScore(summary.min_confidence, 0)} – ${formatScore(summary.max_confidence, 0)}`,
    },
    {
      label: `Below ${formatScore(summary.low_confidence_cutoff, 0)}`,
      value: `${formatNumber(summary.low_confidence)} (${formatPct(summary.low_confidence_pct)})`,
    },
    { label: "Avg on resolved", value: formatScore(summary.avg_confidence_resolved) },
    { label: "Avg on false positives", value: formatScore(summary.avg_confidence_false_positive) },
  ];

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle2">Model confidence audit</Typography>
        <Typography variant="caption" color="text.secondary">
          Detector confidence of {formatNumber(summary.scored_events)} scored alerts. Operator
          verdicts stand in for ground truth: false positives clustering at low confidence point to
          the threshold, high-confidence ones to the scene.
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
                Detector threshold {formatScore(summary.threshold, 0)}; the tracker decides which
                detections start a track.
              </Typography>
            </Stack>
          </Grid>
        </Grid>
      </CardContent>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Camera</TableCell>
              <TableCell align="right">Scored alerts</TableCell>
              <TableCell align="right">Avg</TableCell>
              <TableCell align="right">Min – max</TableCell>
              <TableCell align="right">Low confidence</TableCell>
              <TableCell align="right">False positives</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {audit.by_camera.map((row) => (
              <TableRow key={row.camera_id || "deleted"} hover>
                <TableCell>{row.camera_name || "Deleted camera"}</TableCell>
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
            label: "Alerts",
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
            label: "False positives",
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
  }, [summary, hourly, theme, baseOptions, dismissed]);

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
        labels: rows.map((row) => row.camera_name || "Deleted camera"),
        datasets: [
          {
            label: "Alerts",
            data: rows.map((row) => row.events - row.false_positives),
            backgroundColor: theme.palette.primary.main,
            ...segment,
          },
          {
            label: "False positives",
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
  }, [summary, theme, baseOptions, dismissed]);

  const byClass = useMemo(() => {
    const rows = summary?.by_class || [];
    return {
      height: Math.max(160, rows.length * 30 + 24),
      data: {
        labels: rows.map((row) => titleCase(row.class_name)),
        datasets: [
          {
            label: "Alerts",
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
                return `avg confidence ${confidence} · ${row.false_positives} false positive${row.false_positives === 1 ? "" : "s"}`;
              },
            },
          },
        },
      },
    };
  }, [summary, theme, baseOptions]);

  const funnel = summary?.funnel;
  const funnelStages = funnel
    ? [
        { key: "detected", label: "Alerts raised", value: funnel.events_detected },
        {
          key: "harvested",
          label: "Added to found gallery",
          value: funnel.items_harvested,
          caption: funnel.events_detected
            ? `${formatPct(share(funnel.items_harvested, funnel.events_detected))} of alerts`
            : null,
        },
        {
          key: "reports",
          label: "Lost reports filed",
          value: funnel.reports_filed,
          caption: cameraId ? "All cameras — a report is not tied to one" : null,
        },
        {
          key: "reunions",
          label: "Reunited with owner",
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
        title="Analytics"
        subtitle={`What the cameras flagged, when, where, and how much of it got back to its owner. Times in ${TIMEZONE}.`}
        actions={
          <>
            <TextField
              select
              size="small"
              label="Camera"
              value={cameraId}
              onChange={(event) => setCameraId(event.target.value)}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">All cameras</MenuItem>
              {(cameraList.data || []).map((camera) => (
                <MenuItem key={camera.camera_id} value={camera.camera_id}>
                  {camera.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="Window"
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

      <ErrorState error={error} onRetry={refresh} title="Could not load analytics" />

      {!summary && loading ? (
        <Loading label="Aggregating…" height={360} />
      ) : summary ? (
        // A refetch dims the previous numbers instead of blanking the page.
        <Box sx={{ opacity: loading ? 0.55 : 1, transition: "opacity 150ms" }}>
          <Grid container spacing={2} sx={{ mb: 2 }}>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label="Alerts"
                value={formatNumber(kpis.events)}
                hint={`${formatNumber(kpis.open)} still open`}
                icon={<NotificationsIcon />}
                color="warning"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label="False-positive rate"
                value={formatPct(kpis.false_positive_pct)}
                hint={`${formatNumber(kpis.false_positives)} dismissed`}
                icon={<BlockIcon />}
                color="secondary"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label="Items reunited"
                value={formatNumber(kpis.reunions)}
                hint={`of ${formatNumber(kpis.lost_reports)} reports filed`}
                icon={<HandshakeIcon />}
                color="success"
              />
            </Grid>
            <Grid size={{ xs: 6, md: 3 }}>
              <StatCard
                label="Median time to reunite"
                value={formatDuration(kpis.median_reunite_s)}
                hint={
                  kpis.fastest_reunite_s !== null
                    ? `fastest ${formatDuration(kpis.fastest_reunite_s)}`
                    : "no reunions in this window"
                }
                icon={<TimerIcon />}
                color="info"
              />
            </Grid>
          </Grid>

          {!hasEvents ? (
            <Card>
              <EmptyState
                title={`No alerts in the ${windowLabel}`}
                description="Nothing was left unattended long enough to raise an alert. Try a longer window or another camera."
              />
            </Card>
          ) : (
            <Grid container spacing={2}>
              <Grid size={12}>
                <ChartCard
                  title={hourly ? "Alerts per hour" : "Alerts per day"}
                  subtitle={`${formatNumber(kpis.events)} alerts, ${formatNumber(kpis.false_positives)} dismissed as false positives`}
                >
                  <Box sx={{ height: 280 }}>
                    <Line data={trend.data} options={trend.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 6 }}>
                <ChartCard
                  title="By camera"
                  subtitle={
                    summary.by_camera.length > CAMERA_CHART_LIMIT
                      ? `Top ${CAMERA_CHART_LIMIT} of ${summary.by_camera.length} — every camera is in the table below`
                      : "Valid alerts and false positives per camera"
                  }
                >
                  <Box sx={{ height: byCamera.height }}>
                    <Bar data={byCamera.data} options={byCamera.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 6 }}>
                <ChartCard title="By object type" subtitle="Alerts per detected class">
                  <Box sx={{ height: byClass.height }}>
                    <Bar data={byClass.data} options={byClass.options} />
                  </Box>
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 8 }}>
                <ChartCard
                  title="When items are left"
                  subtitle="Alerts by weekday and hour of day — hover a cell for the count"
                >
                  <HourHeatmap cells={summary.heatmap} />
                </ChartCard>
              </Grid>

              <Grid size={{ xs: 12, lg: 4 }}>
                <ChartCard title="Reunion funnel" subtitle={`Over the ${windowLabel}`}>
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
                    title="Could not load the confidence audit"
                  />
                )}
              </Grid>

              <Grid size={12}>
                <Card>
                  <CardContent sx={{ pb: 0 }}>
                    <Typography variant="subtitle2">Camera breakdown</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Unattended is how long an object sat still with no owner before the alert
                      fired.
                    </Typography>
                  </CardContent>
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Camera</TableCell>
                          <TableCell>Location</TableCell>
                          <TableCell align="right">Alerts</TableCell>
                          <TableCell align="right">Open</TableCell>
                          <TableCell align="right">False positives</TableCell>
                          <TableCell align="right">Avg unattended</TableCell>
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
                                {row.camera_name || "Deleted camera"}
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
