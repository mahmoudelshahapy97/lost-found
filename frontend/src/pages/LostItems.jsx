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

import AddAPhotoIcon from "@mui/icons-material/AddAPhoto";
import RefreshIcon from "@mui/icons-material/Refresh";
import ReportProblemIcon from "@mui/icons-material/ReportProblem";

import PageHeader from "../components/PageHeader";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { LostStatusChip } from "../components/StatusChips";
import { lostItems as lostApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { LOST_STATUSES, PAGE_SIZE, PAGE_SIZE_OPTIONS } from "../utils/constants";
import { formatDateTime, fromNow, titleCase } from "../utils/format";

export default function LostItems() {
  const [params, setParams] = useSearchParams();
  const { hasRole } = useAuth();
  const canReport = hasRole("operator");

  const status = params.get("status") || "";
  const page = Math.max(1, Number(params.get("page") || 1));
  const perPage = Number(params.get("per_page") || PAGE_SIZE);

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };

  const { data, error, loading, refresh } = useAsync(
    ({ signal }) =>
      lostApi.list({ ...(status && { status }), page, per_page: perPage }, { signal }),
    [status, page, perPage]
  );

  const rows = data?.lost_items || [];

  return (
    <Box>
      <PageHeader
        title="Lost reports"
        subtitle="What people have told us they are missing."
        actions={[
          canReport && (
            <Button
              key="new"
              component={RouterLink}
              to="/lost-items/new"
              variant="contained"
              startIcon={<AddAPhotoIcon />}
            >
              Report lost item
            </Button>
          ),
          <Button key="refresh" onClick={refresh} startIcon={<RefreshIcon />}>
            Refresh
          </Button>,
        ]}
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            select
            label="Status"
            size="small"
            value={status}
            onChange={(event) => setParam("status", event.target.value)}
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">All statuses</MenuItem>
            {LOST_STATUSES.map((value) => (
              <MenuItem key={value} value={value}>
                {titleCase(value)}
              </MenuItem>
            ))}
          </TextField>
          <Box sx={{ flex: 1 }} />
          {status ? <Button onClick={() => setParam("status", "")}>Clear</Button> : null}
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} />

      {loading && !data ? (
        <Loading label="Loading reports…" />
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Description</TableCell>
                  <TableCell>Reporter</TableCell>
                  <TableCell>Object</TableCell>
                  <TableCell>Colour</TableCell>
                  <TableCell>Reported</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right" />
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((item) => (
                  <TableRow key={item.lost_id} hover>
                    <TableCell sx={{ maxWidth: 340 }}>
                      <Link
                        component={RouterLink}
                        to={`/lost-items/${item.lost_id}`}
                        underline="hover"
                        sx={{ fontWeight: 600 }}
                      >
                        {item.description || "Photo-only report"}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {item.reporter_name || "—"}
                      </Typography>
                      {item.reporter_email ? (
                        <Typography variant="caption" color="text.disabled" display="block">
                          {item.reporter_email}
                        </Typography>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {item.class_name ? titleCase(item.class_name) : "Unspecified"}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {item.dominant_color ? titleCase(item.dominant_color) : "—"}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={formatDateTime(item.reported_at)}>
                        <Typography variant="body2" color="text.secondary">
                          {fromNow(item.reported_at)}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <LostStatusChip status={item.status} />
                    </TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        component={RouterLink}
                        to={`/lost-items/${item.lost_id}`}
                      >
                        Find matches
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
            title={status ? "No reports with this status" : "No lost items reported"}
            description="A report with a photo is embedded into the same vector space as the crops harvested from the cameras — that shared space is what makes matching possible."
            icon={<ReportProblemIcon fontSize="inherit" />}
            action={
              canReport && (
                <Button
                  component={RouterLink}
                  to="/lost-items/new"
                  variant="contained"
                  startIcon={<AddAPhotoIcon />}
                >
                  Report lost item
                </Button>
              )
            }
          />
        </Card>
      )}
    </Box>
  );
}
