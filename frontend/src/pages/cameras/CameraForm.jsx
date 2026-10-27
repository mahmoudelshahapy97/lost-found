import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Grid from "@mui/material/Grid2";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";

import { errorMessage } from "../../api/client";
import { cameras as camerasApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { parseJsonField } from "../../utils/format";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

const EMPTY = {
  name: "",
  location: "",
  rtsp_url: "",
  enabled: true,
  abandon_seconds: "",
  owner_distance_px: "",
  abandon_distance_px: "",
  static_tolerance_px: "",
};

/**
 * The tuning knobs a camera may override, mirroring AbandonmentParams. They
 * live in the `settings` jsonb rather than in columns of their own, so an
 * absent key means "inherit the global .env value" — a different thing from 0,
 * which is why blanks are omitted from the payload rather than sent as zero.
 */
const OVERRIDE_FIELDS = [
  {
    key: "abandon_seconds",
    get label() { return i18n.t("cameraForm.abandonAfter"); },
    unit: "s",
    get help() { return i18n.t("cameraForm.unattendedTimeBeforeAnAlert"); },
    min: 1,
    max: 3600,
  },
  {
    key: "owner_distance_px",
    get label() { return i18n.t("cameraForm.ownerRadius"); },
    unit: "px",
    get help() { return i18n.t("cameraForm.theNearestPersonWithinThis"); },
    min: 1,
    max: 4000,
  },
  {
    key: "abandon_distance_px",
    get label() { return i18n.t("cameraForm.abandonRadius"); },
    unit: "px",
    get help() { return i18n.t("cameraForm.onceTheOwnerIsFurther"); },
    min: 1,
    max: 4000,
  },
  {
    key: "static_tolerance_px",
    get label() { return i18n.t("cameraForm.staticTolerance"); },
    unit: "px",
    get help() { return i18n.t("cameraForm.howFarACentroidMay"); },
    min: 1,
    max: 1000,
  },
];

function validate(values) {
  const errors = {};
  if (!values.name.trim()) errors.name = i18n.t("cameraForm.required");
  else if (values.name.length > 120) errors.name = i18n.t("cameraForm.atMost120Characters");

  if (!values.rtsp_url.trim()) errors.rtsp_url = i18n.t("cameraForm.required");
  if (values.location.length > 200) errors.location = i18n.t("cameraForm.atMost200Characters");

  OVERRIDE_FIELDS.forEach(({ key, min, max }) => {
    const raw = values[key];
    if (raw === "" || raw === null || raw === undefined) return;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[key] = i18n.t("cameraForm.mustBeANumber");
    else if (value < min || value > max) errors[key] = i18n.t("cameraForm.betweenMinAndMax", { min, max });
  });

  // The backend validates neither of these against the other, but an abandon
  // radius inside the owner radius means the owner is "away" the instant they
  // are found — every stationary bag would alert.
  const owner = values.owner_distance_px === "" ? null : Number(values.owner_distance_px);
  const abandon = values.abandon_distance_px === "" ? null : Number(values.abandon_distance_px);
  if (owner !== null && abandon !== null && abandon <= owner) {
    errors.abandon_distance_px = i18n.t("cameraForm.mustBeGreaterThanThe");
  }

  return errors;
}

export default function CameraForm() {
  const { t } = useTranslation();
  const { cameraId } = useParams();
  const isEdit = Boolean(cameraId);
  const navigate = useNavigate();
  const toast = useToast();

  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const {
    data: camera,
    error: loadError,
    loading,
    refresh,
  } = useAsync(({ signal }) => camerasApi.get(cameraId, { signal }), [cameraId], {
    enabled: isEdit,
  });

  useEffect(() => {
    if (!camera) return;
    const settings = parseJsonField(camera.settings, {}) || {};
    setValues({
      name: camera.name ?? "",
      location: camera.location ?? "",
      rtsp_url: camera.rtsp_url ?? "",
      enabled: camera.enabled ?? true,
      abandon_seconds: settings.abandon_seconds ?? "",
      owner_distance_px: settings.owner_distance_px ?? "",
      abandon_distance_px: settings.abandon_distance_px ?? "",
      static_tolerance_px: settings.static_tolerance_px ?? "",
    });
  }, [camera]);

  const setField = (field) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const payload = useMemo(() => {
    const settings = {};
    OVERRIDE_FIELDS.forEach(({ key }) => {
      const raw = values[key];
      // Omitted, not zeroed: an absent key is what "inherit the default" means.
      if (raw !== "" && raw !== null && raw !== undefined) settings[key] = Number(raw);
    });

    return {
      name: values.name.trim(),
      rtsp_url: values.rtsp_url.trim(),
      location: values.location.trim() || null,
      enabled: values.enabled,
      settings,
    };
  }, [values]);

  const submit = async (event) => {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length) return;

    setSaving(true);
    setSubmitError(null);
    try {
      if (isEdit) {
        await camerasApi.update(cameraId, payload);
        toast.success(t("cameraForm.cameraNameUpdated", { name: payload.name }));
        navigate(`/cameras/${cameraId}`);
      } else {
        const created = await camerasApi.create(payload);
        toast.success(t("cameraForm.cameraNameRegistered", { name: created.name }));
        navigate(`/cameras/${created.camera_id}`);
      }
    } catch (err) {
      setSubmitError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (isEdit && loading && !camera) return <Loading label={t("cameraForm.loadingCamera")} />;
  if (isEdit && loadError) return <ErrorState error={loadError} onRetry={refresh} />;

  return (
    <Box>
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate(isEdit ? `/cameras/${cameraId}` : "/cameras")}
        sx={{ mb: 2 }}
      >
        {t("cameraForm.back")}
      </Button>

      <PageHeader
        title={isEdit ? t("cameraForm.editV0", { v0: camera?.name || "camera" }) : t("cameraForm.registerACamera")}
        subtitle={
          isEdit
            ? t("cameraForm.aRunningWorkerIsRestarted")
            : t("cameraForm.anEnabledCameraStartsIts")
        }
      />

      <Box component="form" onSubmit={submit} noValidate>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 7 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>
                  {t("cameraForm.source")}
                </Typography>
                <Stack spacing={2.5}>
                  <TextField
                    label={t("cameraForm.name")}
                    value={values.name}
                    onChange={setField("name")}
                    error={Boolean(errors.name)}
                    helperText={errors.name || t("cameraForm.mustBeUniqueWithinThis")}
                    required
                    fullWidth
                    autoFocus
                  />
                  <TextField
                    label={t("cameraForm.rtspUrl")}
                    value={values.rtsp_url}
                    onChange={setField("rtsp_url")}
                    error={Boolean(errors.rtsp_url)}
                    helperText={
                      errors.rtsp_url ||
                      t("cameraForm.rtspUserPassHost554")
                    }
                    required
                    fullWidth
                    placeholder={t("cameraForm.rtspMediamtx8554Lostfound")}
                  />
                  <TextField
                    label={t("cameraForm.location")}
                    value={values.location}
                    onChange={setField("location")}
                    error={Boolean(errors.location)}
                    helperText={errors.location || t("cameraForm.whereAnOperatorWouldPhysically")}
                    fullWidth
                    placeholder={t("cameraForm.terminal1GroundFloor")}
                  />
                  <FormControlLabel
                    control={<Switch checked={values.enabled} onChange={setField("enabled")} />}
                    label={t("cameraForm.enabled")}
                  />
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 5 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  {t("cameraForm.thresholds")}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
                  {t("cameraForm.leaveAFieldBlankTo")}
                </Typography>
                <Divider sx={{ mb: 2.5 }} />
                <Stack spacing={2.5}>
                  {OVERRIDE_FIELDS.map(({ key, label, unit, help }) => (
                    <TextField
                      key={key}
                      label={label}
                      value={values[key]}
                      onChange={setField(key)}
                      error={Boolean(errors[key])}
                      helperText={errors[key] || help}
                      type="number"
                      fullWidth
                      slotProps={{
                        input: {
                          endAdornment: <InputAdornment position="end">{unit}</InputAdornment>,
                        },
                      }}
                    />
                  ))}
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={12}>
            {submitError ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                {submitError}
              </Alert>
            ) : null}
            <Stack direction="row" spacing={1}>
              <Button type="submit" variant="contained" disabled={saving}>
                {saving ? t("cameraForm.saving") : isEdit ? t("cameraForm.saveChanges") : t("cameraForm.registerCamera")}
              </Button>
              <Button
                color="inherit"
                disabled={saving}
                onClick={() => navigate(isEdit ? `/cameras/${cameraId}` : "/cameras")}
              >
                {t("cameraForm.cancel")}
              </Button>
            </Stack>
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}
