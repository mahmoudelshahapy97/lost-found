import { Link as RouterLink, useSearchParams } from "react-router-dom";
import dayjs from "dayjs";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
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
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";

import AccessTimeIcon from "@mui/icons-material/AccessTime";
import CalendarTodayIcon from "@mui/icons-material/CalendarToday";
import ClearIcon from "@mui/icons-material/Clear";
import GridViewIcon from "@mui/icons-material/GridView";
import ImageSearchIcon from "@mui/icons-material/ImageSearch";
import RefreshIcon from "@mui/icons-material/Refresh";
import TableRowsIcon from "@mui/icons-material/TableRows";
import VideocamIcon from "@mui/icons-material/Videocam";

import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { FoundStatusChip } from "../components/StatusChips";
import { cameras as cameraApi, foundItems as foundApi } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { FOUND_STATUSES, ITEM_COLORS, OBJECT_CLASSES, PAGE_SIZE_OPTIONS } from "../utils/constants";
import {
  formatDate,
  formatTime,
  fromDateTimeLocal,
  titleCase,
  toDateTimeLocal,
} from "../utils/format";

/** One-click ranges; the From/To fields stay editable afterwards. */
const QUICK_RANGES = [
  { label: "Last hour", from: () => dayjs().subtract(1, "hour") },
  { label: "Today", from: () => dayjs().startOf("day") },
  { label: "Last 24 h", from: () => dayjs().subtract(24, "hour") },
  { label: "Last 7 days", from: () => dayjs().subtract(7, "day") },
];

const FILTER_KEYS = ["camera_id", "class_name", "color", "status", "start", "end"];

/**
 * Search the found gallery by camera, date/time, object type, colour and status.
 *
 * Plain filters over indexed columns, so it answers instantly with no models.
 * Filters live in the URL rather than component state: a search survives a
 * reload and can be shared or linked to.
 */
export default function Search() {
  const [params, setParams] = useSearchParams();

  const cameraId = params.get("camera_id") || "";
  const className = params.get("class_name") || "";
  const color = params.get("color") || "";
  const status = params.get("status") || "";
  const start = params.get("start") || "";
  const end = params.get("end") || "";
  const view = params.get("view") === "table" ? "table" : "cards";
  const page = Math.max(1, Number(params.get("page") || 1));
  const perPage = Number(params.get("per_page") || 24);

  const setParam = (updates) => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([key, value]) => {
      if (value) next.set(key, value);
      else next.delete(key);
    });
    // Any filter change invalidates the page we were on.
    if (!("page" in updates) && !("view" in updates)) next.delete("page");
    setParams(next, { replace: true });
  };

  const clearFilters = () => {
    const next = new URLSearchParams(params);
    [...FILTER_KEYS, "page"].forEach((key) => next.delete(key));
    setParams(next, { replace: true });
  };

  const rangeInvalid = Boolean(start && end && dayjs(start).isAfter(dayjs(end)));
  const hasFilters = FILTER_KEYS.some((key) => params.get(key));

  const { data, error, loading, refresh } = useAsync(
    ({ signal }) =>
      foundApi.list(
        {
          ...(cameraId && { camera_id: cameraId }),
          ...(className && { class_name: className }),
          ...(color && { color }),
          ...(status && { status }),
          ...(start && { start }),
          ...(end && { end }),
          page,
          per_page: perPage,
        },
        { signal }
      ),
    [cameraId, className, color, status, start, end, page, perPage],
    { enabled: !rangeInvalid }
  );

  const cameraList = useAsync(({ signal }) => cameraApi.list(undefined, { signal }), []);

  const items = data?.found_items || [];
  const total = data?.total ?? 0;

  return (
    <Box>
      <PageHeader
        title="Search the found gallery"
        subtitle="Filter every harvested item by camera, date and time, object type and colour."
        actions={[
          hasFilters ? (
            <Button key="clear" onClick={clearFilters} startIcon={<ClearIcon />}>
              Clear filters
            </Button>
          ) : null,
          <Button key="refresh" onClick={refresh} startIcon={<RefreshIcon />}>
            Refresh
          </Button>,
        ].filter(Boolean)}
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              select
              label="Camera"
              size="small"
              fullWidth
              value={cameraId}
              onChange={(event) => setParam({ camera_id: event.target.value })}
            >
              <MenuItem value="">All cameras</MenuItem>
              {(cameraList.data || []).map((camera) => (
                <MenuItem key={camera.camera_id} value={camera.camera_id}>
                  {camera.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              type="datetime-local"
              label="From"
              size="small"
              fullWidth
              value={toDateTimeLocal(start)}
              onChange={(event) => setParam({ start: fromDateTimeLocal(event.target.value) })}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              type="datetime-local"
              label="To"
              size="small"
              fullWidth
              value={toDateTimeLocal(end)}
              onChange={(event) => setParam({ end: fromDateTimeLocal(event.target.value) })}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              select
              label="Object type"
              size="small"
              fullWidth
              value={className}
              onChange={(event) => setParam({ class_name: event.target.value })}
            >
              <MenuItem value="">Any type</MenuItem>
              {OBJECT_CLASSES.map((value) => (
                <MenuItem key={value} value={value}>
                  {titleCase(value)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              select
              label="Colour"
              size="small"
              fullWidth
              value={color}
              onChange={(event) => setParam({ color: event.target.value })}
            >
              <MenuItem value="">Any colour</MenuItem>
              {ITEM_COLORS.map((value) => (
                <MenuItem key={value} value={value}>
                  {titleCase(value)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6, md: 4 }}>
            <TextField
              select
              label="Status"
              size="small"
              fullWidth
              value={status}
              onChange={(event) => setParam({ status: event.target.value })}
            >
              <MenuItem value="">All statuses</MenuItem>
              {FOUND_STATUSES.map((value) => (
                <MenuItem key={value} value={value}>
                  {titleCase(value)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
        </Grid>

        <Stack direction="row" spacing={1} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
          {QUICK_RANGES.map((range) => (
            <Chip
              key={range.label}
              label={range.label}
              size="small"
              variant="outlined"
              clickable
              onClick={() => setParam({ start: range.from().toISOString(), end: "" })}
            />
          ))}
        </Stack>
      </Card>

      {rangeInvalid ? (
        <Alert severity="warning" sx={{ mb: 2 }}>
          &quot;From&quot; is after &quot;To&quot; — adjust the range to search.
        </Alert>
      ) : null}

      <ErrorState error={error} onRetry={refresh} />

      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {data ? (
            <>
              <strong>{total}</strong> {total === 1 ? "item" : "items"} found
            </>
          ) : null}
        </Typography>
        <ToggleButtonGroup
          size="small"
          exclusive
          value={view}
          onChange={(_, next) => next && setParam({ view: next === "cards" ? "" : next })}
          aria-label="Result view"
        >
          <ToggleButton value="cards" aria-label="Cards">
            <GridViewIcon fontSize="small" />
          </ToggleButton>
          <ToggleButton value="table" aria-label="Table">
            <TableRowsIcon fontSize="small" />
          </ToggleButton>
        </ToggleButtonGroup>
      </Stack>

      {loading && !data ? (
        <Loading label="Searching…" />
      ) : items.length ? (
        <>
          {view === "cards" ? <ResultCards items={items} /> : <ResultTable items={items} />}

          <Card sx={{ mt: 2 }}>
            <TablePagination
              component="div"
              count={total}
              page={page - 1}
              rowsPerPage={perPage}
              rowsPerPageOptions={[...PAGE_SIZE_OPTIONS, 24].sort((a, b) => a - b)}
              onPageChange={(_, nextPage) => setParam({ page: String(nextPage + 1) })}
              onRowsPerPageChange={(event) => setParam({ per_page: event.target.value })}
            />
          </Card>
        </>
      ) : (
        <Card>
          <EmptyState
            title={hasFilters ? "Nothing matches these filters" : "The gallery is empty"}
            description={
              hasFilters
                ? "Widen the time range, or pick another camera, type or colour."
                : "Items land here automatically whenever a camera raises an abandoned-object alert."
            }
            icon={<ImageSearchIcon fontSize="inherit" />}
            action={
              hasFilters ? (
                <Button variant="outlined" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : null
            }
          />
        </Card>
      )}
    </Box>
  );
}

function CameraLabel({ item }) {
  if (!item.camera_id) return "Camera deleted";
  return (
    <Link component={RouterLink} to={`/cameras/${item.camera_id}`} underline="hover" color="inherit">
      {item.camera_name || "Unnamed camera"}
    </Link>
  );
}

function ResultCards({ items }) {
  return (
    <Grid container spacing={2}>
      {items.map((item) => (
        <Grid key={item.found_id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
          <Card sx={{ height: "100%" }} data-testid="search-result">
            <ItemImage
              src={foundApi.cropUrl(item.found_id)}
              alt={`Found ${item.class_name}`}
              height={180}
              fallbackLabel="No crop stored"
            />
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
                <Typography variant="subtitle2">{titleCase(item.class_name)}</Typography>
                <FoundStatusChip status={item.status} />
              </Stack>

              <Stack spacing={0.5}>
                <Stack direction="row" spacing={1} alignItems="center" color="text.secondary">
                  <VideocamIcon sx={{ fontSize: 16 }} />
                  <Typography variant="caption">
                    <CameraLabel item={item} />
                  </Typography>
                </Stack>
                <Stack direction="row" spacing={2} color="text.secondary">
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <CalendarTodayIcon sx={{ fontSize: 14 }} />
                    <Typography variant="caption">{formatDate(item.found_at)}</Typography>
                  </Stack>
                  <Stack direction="row" spacing={0.5} alignItems="center">
                    <AccessTimeIcon sx={{ fontSize: 14 }} />
                    <Typography variant="caption">{formatTime(item.found_at)}</Typography>
                  </Stack>
                </Stack>
              </Stack>

              <Stack direction="row" spacing={0.5} sx={{ mt: 1.5 }} flexWrap="wrap" useFlexGap>
                {item.dominant_color ? (
                  <Chip size="small" variant="outlined" label={titleCase(item.dominant_color)} />
                ) : null}
                {item.event_id ? (
                  <Chip
                    size="small"
                    variant="outlined"
                    clickable
                    component={RouterLink}
                    to={`/events/${item.event_id}`}
                    label="View alert"
                  />
                ) : null}
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  );
}

function ResultTable({ items }) {
  return (
    <Card>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 88 }}>Crop</TableCell>
              <TableCell>Object</TableCell>
              <TableCell>Colour</TableCell>
              <TableCell>Camera</TableCell>
              <TableCell>Date</TableCell>
              <TableCell>Time</TableCell>
              <TableCell>Status</TableCell>
              <TableCell align="right" />
            </TableRow>
          </TableHead>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.found_id} hover data-testid="search-result">
                <TableCell>
                  <ItemImage
                    src={foundApi.cropUrl(item.found_id)}
                    alt={`Found ${item.class_name}`}
                    height={48}
                    fallbackLabel="—"
                    sx={{ width: 64, borderRadius: 0.5 }}
                  />
                </TableCell>
                <TableCell>{titleCase(item.class_name)}</TableCell>
                <TableCell>{item.dominant_color ? titleCase(item.dominant_color) : "—"}</TableCell>
                <TableCell>
                  <CameraLabel item={item} />
                </TableCell>
                <TableCell>{formatDate(item.found_at)}</TableCell>
                <TableCell>{formatTime(item.found_at)}</TableCell>
                <TableCell>
                  <FoundStatusChip status={item.status} />
                </TableCell>
                <TableCell align="right">
                  {item.event_id ? (
                    <Link component={RouterLink} to={`/events/${item.event_id}`} underline="hover">
                      View alert
                    </Link>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Card>
  );
}
