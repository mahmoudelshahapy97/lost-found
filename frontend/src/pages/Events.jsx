import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import NotificationsIcon from "@mui/icons-material/NotificationsActive";
import RefreshIcon from "@mui/icons-material/Refresh";

import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { EventStatusChip } from "../components/StatusChips";
import { cameras as cameraApi, events as eventApi } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import {
  EVENT_STATUSES,
  OBJECT_CLASSES,
  PAGE_SIZE,
  PAGE_SIZE_OPTIONS,
} from "../utils/constants";
import { formatDateTime, formatScore, fromNow, titleCase } from "../utils/format";

/**
 * Filters live in the query string rather than in component state, so a
 * filtered view is a real URL: it survives a reload, works with back/forward,
 * and can be linked to from the dashboard and from a camera's detail page.
 */
export default function Events() {
  const [params, setParams] = useSearchParams();

  const status = params.get("status") || "";
  const className = params.get("class_name") || "";
  const cameraId = params.get("camera_id") || "";
  const page = Math.max(1, Number(params.get("page") || 1));
  const perPage = Number(params.get("per_page") || PAGE_SIZE);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    // Any filter change invalidates the current offset.
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  const { data, error, loading, refresh } = useAsync(
    ({ signal }) =>
      eventApi.list(
        {
          ...(status && { status }),
          ...(className && { class_name: className }),
          ...(cameraId && { camera_id: cameraId }),
          page,
          per_page: perPage,
        },
        { signal }
      ),
    [status, className, cameraId, page, perPage]
  );

  const cameraList = useAsync(({ signal }) => cameraApi.list(undefined, { signal }), []);

  const rows = data?.events || [];
  const hasFilters = Boolean(status || className || cameraId);

  return (
    <Box>
      <PageHeader
        title="Alerts"
        subtitle="Every object a camera worker declared abandoned, newest first."
        actions={[
          <Button key="refresh" onClick={refresh} startIcon={<RefreshIcon />}>
            Refresh
          </Button>,
        ]}
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <TextField
            select
            label="Status"
            size="small"
            value={status}
            onChange={(event) => setParam("status", event.target.value)}
            sx={{ minWidth: 180 }}
          >
            <MenuItem value="">All statuses</MenuItem>
            {EVENT_STATUSES.map((value) => (
              <MenuItem key={value} value={value}>
                {titleCase(value)}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label="Object"
            size="small"
            value={className}
            onChange={(event) => setParam("class_name", event.target.value)}
            sx={{ minWidth: 180 }}
          >
            <MenuItem value="">All objects</MenuItem>
            {OBJECT_CLASSES.map((value) => (
              <MenuItem key={value} value={value}>
                {titleCase(value)}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label="Camera"
            size="small"
            value={cameraId}
            onChange={(event) => setParam("camera_id", event.target.value)}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">All cameras</MenuItem>
            {(cameraList.data || []).map((camera) => (
              <MenuItem key={camera.camera_id} value={camera.camera_id}>
                {camera.name}
              </MenuItem>
            ))}
          </TextField>

          <Box sx={{ flex: 1 }} />
          {hasFilters ? (
            <Button onClick={() => setParams(new URLSearchParams())}>Clear filters</Button>
          ) : null}
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} />

      {loading && !data ? (
        <Loading label="Loading alerts…" />
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Object</TableCell>
                  <TableCell>Camera</TableCell>
                  <TableCell>Abandoned</TableCell>
                  <TableCell align="right">Confidence</TableCell>
                  <TableCell>Colour</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((event) => (
                  <TableRow key={event.event_id} hover>
                    <TableCell>
                      <Link
                        component={RouterLink}
                        to={`/events/${event.event_id}`}
                        underline="hover"
                        sx={{ fontWeight: 600 }}
                      >
                        {titleCase(event.class_name)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {event.camera_id ? (
                        <Link
                          component={RouterLink}
                          to={`/cameras/${event.camera_id}`}
                          underline="hover"
                          color="text.secondary"
                          variant="body2"
                        >
                          {event.camera_name || "Unnamed"}
                        </Link>
                      ) : (
                        <Typography variant="body2" color="text.disabled">
                          —
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Tooltip title={formatDateTime(event.abandoned_at)}>
                        <Typography variant="body2" color="text.secondary">
                          {fromNow(event.abandoned_at)}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell align="right">
                      <Typography variant="caption">{formatScore(event.confidence)}</Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {event.dominant_color ? titleCase(event.dominant_color) : "—"}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <EventStatusChip status={event.status} />
                    </TableCell>
                    <TableCell align="right">
                      <Button size="small" component={RouterLink} to={`/events/${event.event_id}`}>
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <TablePagination
            component="div"
            count={data?.total ?? 0}
            page={page - 1}
            rowsPerPage={perPage}
            rowsPerPageOptions={PAGE_SIZE_OPTIONS}
            onPageChange={(_, nextPage) => setParam("page", String(nextPage + 1))}
            onRowsPerPageChange={(event) => setParam("per_page", event.target.value)}
          />
        </Card>
      ) : (
        <Card>
          <EmptyState
            title={hasFilters ? "Nothing matches these filters" : "No alerts yet"}
            description={
              hasFilters
                ? "Try widening the status, object or camera filter."
                : "Alerts appear here as soon as a worker declares an object abandoned."
            }
            icon={<NotificationsIcon fontSize="inherit" />}
            action={
              hasFilters ? (
                <Button variant="outlined" onClick={() => setParams(new URLSearchParams())}>
                  Clear filters
                </Button>
              ) : (
                <Button variant="outlined" component={RouterLink} to="/cameras">
                  Check cameras
                </Button>
              )
            }
          />
        </Card>
      )}
    </Box>
  );
}
