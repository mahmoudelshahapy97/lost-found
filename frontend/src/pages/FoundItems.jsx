import { useState } from "react";
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
import { useToast } from "../components/Toast";
import { errorMessage } from "../api/client";
import { cameras as cameraApi, foundItems as foundApi } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { FOUND_STATUS, FOUND_STATUSES, PAGE_SIZE_OPTIONS } from "../utils/constants";
import { formatDateTime, fromNow, titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";

/**
 * The gallery is a grid rather than a table: these rows are pictures, and the
 * picture is the thing an operator is actually comparing against a report.
 */
export default function FoundItems() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("operator");
  const [busyId, setBusyId] = useState(null);

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

  const changeStatus = async (found, nextStatus) => {
    setBusyId(found.found_id);
    try {
      await foundApi.setStatus(found.found_id, nextStatus);
      toast.success(
        nextStatus === FOUND_STATUS.DISCARDED
          ? t("foundItems.v0DiscardedFromTheGallery", { v0: titleCase(found.class_name) })
          : t("foundItems.v0RestoredAsUnclaimed", { v0: titleCase(found.class_name) })
      );
      refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const cameraList = useAsync(({ signal }) => cameraApi.list(undefined, { signal }), []);

  const items = data?.found_items || [];
  const hasFilters = Boolean(status || cameraId);

  return (
    <Box>
      <PageHeader
        title={t("foundItems.foundGallery")}
        subtitle={t("foundItems.everyObjectHarvestedFromAn")}
        actions={[
          <Button key="refresh" onClick={refresh} startIcon={<RefreshIcon />}>
            {t("foundItems.refresh")}
          </Button>,
        ]}
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <TextField
            select
            label={t("foundItems.status")}
            size="small"
            value={status}
            onChange={(event) => setParam("status", event.target.value)}
            sx={{ minWidth: 180 }}
          >
            <MenuItem value="">{t("foundItems.allStatuses")}</MenuItem>
            {FOUND_STATUSES.map((value) => (
              <MenuItem key={value} value={value}>
                {titleCase(value)}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label={t("foundItems.camera")}
            size="small"
            value={cameraId}
            onChange={(event) => setParam("camera_id", event.target.value)}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">{t("foundItems.allCameras")}</MenuItem>
            {(cameraList.data || []).map((camera) => (
              <MenuItem key={camera.camera_id} value={camera.camera_id}>
                {camera.name}
              </MenuItem>
            ))}
          </TextField>

          <Box sx={{ flex: 1 }} />
          {hasFilters ? (
            <Button onClick={() => setParams(new URLSearchParams())}>{t("foundItems.clearFilters")}</Button>
          ) : null}
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} />

      {loading && !data ? (
        <Loading label={t("foundItems.loadingTheGallery")} />
      ) : items.length ? (
        <>
          <Grid container spacing={2}>
            {items.map((found) => (
              <Grid key={found.found_id} size={{ xs: 12, sm: 6, md: 4, lg: 3 }}>
                <Card sx={{ height: "100%" }} data-testid="found-card" data-found-id={found.found_id}>
                  <ItemImage
                    src={foundApi.cropUrl(found.found_id)}
                    alt={t("foundItems.foundClassName", { class_name: found.class_name })}
                    height={180}
                    fallbackLabel={t("foundItems.noCrop")}
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
                        {t("foundItems.foundV0", { v0: fromNow(found.found_at) })}
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
                          {found.camera_name || t("foundItems.unnamedCamera")}
                        </Link>
                      ) : (
                        t("foundItems.cameraDeleted")
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
                          label={t("foundItems.viewAlert")}
                        />
                      ) : null}
                      {canEdit && found.status === FOUND_STATUS.UNCLAIMED ? (
                        <Chip
                          size="small"
                          variant="outlined"
                          clickable
                          disabled={busyId === found.found_id}
                          onClick={() => changeStatus(found, FOUND_STATUS.DISCARDED)}
                          label={t("foundItems.discard")}
                        />
                      ) : null}
                      {canEdit && found.status === FOUND_STATUS.DISCARDED ? (
                        <Chip
                          size="small"
                          variant="outlined"
                          color="primary"
                          clickable
                          disabled={busyId === found.found_id}
                          onClick={() => changeStatus(found, FOUND_STATUS.UNCLAIMED)}
                          label={t("foundItems.restore")}
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
            title={hasFilters ? t("foundItems.nothingMatchesTheseFilters") : t("foundItems.theGalleryIsEmpty")}
            description={t("foundItems.itemsLandHereAutomaticallyEvery")}
            icon={<Inventory2Icon fontSize="inherit" />}
            action={
              hasFilters ? (
                <Button variant="outlined" onClick={() => setParams(new URLSearchParams())}>
                  {t("foundItems.clearFilters")}
                </Button>
              ) : (
                <Button component={RouterLink} to="/events" variant="outlined">
                  {t("foundItems.viewAlerts")}
                </Button>
              )
            }
          />
        </Card>
      )}
    </Box>
  );
}
