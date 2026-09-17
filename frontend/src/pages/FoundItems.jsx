import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TablePagination from "@mui/material/TablePagination";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import Inventory2Icon from "@mui/icons-material/Inventory2";
import RefreshIcon from "@mui/icons-material/Refresh";

import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { FoundStatusChip } from "../components/StatusChips";
import { cameras as cameraApi, foundItems as foundApi } from "../api/endpoints";
import { useAsync } from "../hooks/useAsync";
import { FOUND_STATUSES, PAGE_SIZE_OPTIONS } from "../utils/constants";
import { formatDateTime, fromNow, titleCase } from "../utils/format";

/**
 * The gallery is a grid rather than a table: these rows are pictures, and the
 * picture is the thing an operator is actually comparing against a report.
 */
export default function FoundItems() {
  const [params, setParams] = useSearchParams();

  const status = params.get("status") || "";
  const cameraId = params.get("camera_id") || "";
  const page = Math.max(1, Number(params.get("page") || 1));
  const perPage = Number(params.get("per_page") || 24);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  const { data, error, loading, refresh } = useAsync(
    ({ signal }) =>
      foundApi.list(
        {
          ...(status && { status }),
          ...(cameraId && { camera_id: cameraId }),
          page,
          per_page: perPage,
        },
        { signal }
      ),
    [status, cameraId, page, perPage]
  );

  const cameraList = useAsync(({ signal }) => cameraApi.list(undefined, { signal }), []);

  const items = data?.found_items || [];
  const hasFilters = Boolean(status || cameraId);

  return (
    <Box>
      <PageHeader
        title="Found gallery"
        subtitle="Every object harvested from an alert, cropped and embedded so a lost report can be matched against it."
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
            {FOUND_STATUSES.map((value) => (
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
        <Loading label="Loading the gallery…" />
      ) : items.length ? (
        <>
          <Grid container spacing={2}>
            {items.map((found) => (
              <Grid key={found.found_id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                <Card sx={{ height: "100%" }}>
                  <ItemImage
                    src={foundApi.cropUrl(found.found_id)}
                    alt={`Found ${found.class_name}`}
                    height={180}
                    fallbackLabel="No crop stored"
                  />
                  <CardContent>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      sx={{ mb: 1 }}
                    >
                      <Typography variant="subtitle2">{titleCase(found.class_name)}</Typography>
                      <FoundStatusChip status={found.status} />
                    </Stack>

                    <Tooltip title={formatDateTime(found.found_at)}>
                      <Typography variant="caption" color="text.secondary" display="block">
                        Found {fromNow(found.found_at)}
                      </Typography>
                    </Tooltip>

                    <Typography variant="caption" color="text.disabled" display="block">
                      {found.camera_id ? (
                        <Link
                          component={RouterLink}
                          to={`/cameras/${found.camera_id}`}
                          underline="hover"
                          color="inherit"
                        >
                          {found.camera_name || "Unnamed camera"}
                        </Link>
                      ) : (
                        "Camera deleted"
                      )}
                    </Typography>

                    <Stack direction="row" spacing={0.5} sx={{ mt: 1.5 }} flexWrap="wrap" useFlexGap>
                      {found.dominant_color ? (
                        <Chip size="small" variant="outlined" label={titleCase(found.dominant_color)} />
                      ) : null}
                      {found.event_id ? (
                        <Chip
                          size="small"
                          variant="outlined"
                          clickable
                          component={RouterLink}
                          to={`/events/${found.event_id}`}
                          label="View alert"
                        />
                      ) : null}
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            ))}
          </Grid>

          <Card sx={{ mt: 2 }}>
            <TablePagination
              component="div"
              count={data?.total ?? 0}
              page={page - 1}
              rowsPerPage={perPage}
              rowsPerPageOptions={[...PAGE_SIZE_OPTIONS, 24].sort((a, b) => a - b)}
              onPageChange={(_, nextPage) => setParam("page", String(nextPage + 1))}
              onRowsPerPageChange={(event) => setParam("per_page", event.target.value)}
            />
          </Card>
        </>
      ) : (
        <Card>
          <EmptyState
            title={hasFilters ? "Nothing matches these filters" : "The gallery is empty"}
            description="Items land here automatically: every abandoned-object alert is cropped and embedded, and that crop becomes a searchable found item."
            icon={<Inventory2Icon fontSize="inherit" />}
            action={
              hasFilters ? (
                <Button variant="outlined" onClick={() => setParams(new URLSearchParams())}>
                  Clear filters
                </Button>
              ) : (
                <Button component={RouterLink} to="/events" variant="outlined">
                  View alerts
                </Button>
              )
            }
          />
        </Card>
      )}
    </Box>
  );
}
