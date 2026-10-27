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
import { useTranslation } from "react-i18next";

export default function LostItems() {
  const { t } = useTranslation();
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
        title={t("lostItems.lostReports")}
        subtitle={t("lostItems.whatPeopleHaveToldUs")}
        actions={[
          canReport && (
            <Button
              key="new"
              component={RouterLink}
              to="/lost-items/new"
              variant="contained"
              startIcon={<AddAPhotoIcon />}
            >
              {t("lostItems.reportLostItem")}
            </Button>
          ),
          <Button key="refresh" onClick={refresh} startIcon={<RefreshIcon />}>
            {t("lostItems.refresh")}
          </Button>,
        ]}
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            select
            label={t("lostItems.status")}
            size="small"
            value={status}
            onChange={(event) => setParam("status", event.target.value)}
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">{t("lostItems.allStatuses")}</MenuItem>
            {LOST_STATUSES.map((value) => (
              <MenuItem key={value} value={value}>
                {titleCase(value)}
              </MenuItem>
            ))}
          </TextField>
          <Box sx={{ flex: 1 }} />
          {status ? <Button onClick={() => setParam("status", "")}>{t("lostItems.clear")}</Button> : null}
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} />

      {loading && !data ? (
        <Loading label={t("lostItems.loadingReports")} />
      ) : rows.length ? (
        <Card>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>{t("lostItems.description")}</TableCell>
                  <TableCell>{t("lostItems.reporter")}</TableCell>
                  <TableCell>{t("lostItems.object")}</TableCell>
                  <TableCell>{t("lostItems.colour")}</TableCell>
                  <TableCell>{t("lostItems.reported")}</TableCell>
                  <TableCell>{t("lostItems.status")}</TableCell>
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
                        {item.description || t("lostItems.photoOnlyReport")}
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
                        {item.class_name ? titleCase(item.class_name) : t("lostItems.unspecified")}
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
                        {t("lostItems.findMatches")}
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
            title={status ? t("lostItems.noReportsWithThisStatus") : t("lostItems.noLostItemsReported")}
            description={t("lostItems.aReportIsMatchedAgainst")}
            icon={<ReportProblemIcon fontSize="inherit" />}
            action={
              canReport && (
                <Button
                  component={RouterLink}
                  to="/lost-items/new"
                  variant="contained"
                  startIcon={<AddAPhotoIcon />}
                >
                  {t("lostItems.reportLostItem")}
                </Button>
              )
            }
          />
        </Card>
      )}
    </Box>
  );
}
