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
    label: "Abandon after",
    unit: "s",
    help: "Unattended time before an alert is raised. PETS2006 convention is 30s.",
    min: 1,
    max: 3600,
  },
  {
    key: "owner_distance_px",
    label: "Owner radius",
    unit: "px",
    help: "The nearest person within this distance when the object goes static becomes its owner.",
    min: 1,
    max: 4000,
  },
  {
    key: "abandon_distance_px",
    label: "Abandon radius",
    unit: "px",
    help: "Once the owner is further away than this, the unattended timer starts.",
    min: 1,
    max: 4000,
  },
  {
    key: "static_tolerance_px",
    label: "Static tolerance",
    unit: "px",
    help: "How far a centroid may drift and still count as stationary.",
    min: 1,
    max: 1000,
  },
];

function validate(values) {
  const errors = {};
  if (!values.name.trim()) errors.name = "Required";
  else if (values.name.length > 120) errors.name = "At most 120 characters";

  if (!values.rtsp_url.trim()) errors.rtsp_url = "Required";
  if (values.location.length > 200) errors.location = "At most 200 characters";

  OVERRIDE_FIELDS.forEach(({ key, label, min, max }) => {
    const raw = values[key];
    if (raw === "" || raw === null || raw === undefined) return;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[key] = "Must be a number";
    else if (value < min || value > max) errors[key] = `Between ${min} and ${max}`;
  });

  // The backend validates neither of these against the other, but an abandon
  // radius inside the owner radius means the owner is "away" the instant they
  // are found — every stationary bag would alert.
  const owner = values.owner_distance_px === "" ? null : Number(values.owner_distance_px);
  const abandon = values.abandon_distance_px === "" ? null : Number(values.abandon_distance_px);
  if (owner !== null && abandon !== null && abandon <= owner) {
    errors.abandon_distance_px = "Must be greater than the owner radius";
  }

  return errors;
}

export default function CameraForm() {
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
        toast.success(`Camera "${payload.name}" updated.`);
        navigate(`/cameras/${cameraId}`);
      } else {
        const created = await camerasApi.create(payload);
        toast.success(`Camera "${created.name}" registered.`);
        navigate(`/cameras/${created.camera_id}`);
      }
    } catch (err) {
      setSubmitError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (isEdit && loading && !camera) return <Loading label="Loading camera…" />;
  if (isEdit && loadError) return <ErrorState error={loadError} onRetry={refresh} />;

  return (
    <Box>
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate(isEdit ? `/cameras/${cameraId}` : "/cameras")}
        sx={{ mb: 2 }}
      >
        Back
      </Button>

      <PageHeader
        title={isEdit ? `Edit ${camera?.name || "camera"}` : "Register a camera"}
        subtitle={
          isEdit
            ? "A running worker is restarted when you save, so changes take effect at once."
            : "An enabled camera starts its detection worker as soon as it is saved."
        }
      />

      <Box component="form" onSubmit={submit} noValidate>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 7 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>
                  Source
                </Typography>
                <Stack spacing={2.5}>
                  <TextField
                    label="Name"
                    value={values.name}
                    onChange={setField("name")}
                    error={Boolean(errors.name)}
                    helperText={errors.name || "Must be unique across all cameras."}
                    required
                    fullWidth
                    autoFocus
                  />
                  <TextField
                    label="RTSP URL"
                    value={values.rtsp_url}
                    onChange={setField("rtsp_url")}
                    error={Boolean(errors.rtsp_url)}
                    helperText={
                      errors.rtsp_url ||
                      "rtsp://user:pass@host:554/stream, or a file path inside the API container for testing."
                    }
                    required
                    fullWidth
                    placeholder="rtsp://mediamtx:8554/lostfound"
                  />
                  <TextField
                    label="Location"
                    value={values.location}
                    onChange={setField("location")}
                    error={Boolean(errors.location)}
                    helperText={errors.location || "Where an operator would physically go."}
                    fullWidth
                    placeholder="Terminal 1, Ground Floor"
                  />
                  <FormControlLabel
                    control={<Switch checked={values.enabled} onChange={setField("enabled")} />}
                    label="Enabled"
                  />
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 5 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  Thresholds
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2 }}>
                  Leave a field blank to inherit the global value from the API's environment. A
                  blank is not zero.
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
                {saving ? "Saving…" : isEdit ? "Save changes" : "Register camera"}
              </Button>
              <Button
                color="inherit"
                disabled={saving}
                onClick={() => navigate(isEdit ? `/cameras/${cameraId}` : "/cameras")}
              >
                Cancel
              </Button>
            </Stack>
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}
