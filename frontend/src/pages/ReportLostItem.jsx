import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";

import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { useToast } from "../components/Toast";
import { errorMessage } from "../api/client";
import { lostItems as lostApi } from "../api/endpoints";
import { OBJECT_CLASSES } from "../utils/constants";
import { titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";

/** MAX_UPLOAD_BYTES in backend/.env. Checked here so a 20 MB photo fails at the
 *  file picker rather than after the whole body has been uploaded. */
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const ACCEPTED = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp"];

const EMPTY = {
  description: "",
  reporter_name: "",
  reporter_email: "",
  class_name: "",
  lost_after: "",
};

export default function ReportLostItem() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToast();

  const [values, setValues] = useState(EMPTY);
  const [photo, setPhoto] = useState(null);
  const [preview, setPreview] = useState(null);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [saving, setSaving] = useState(false);

  // Object URLs are not garbage-collected; without this every re-pick leaks a
  // blob for the lifetime of the document.
  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return undefined;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const setField = (field) => (event) => {
    setValues((current) => ({ ...current, [field]: event.target.value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const pickPhoto = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      setErrors((current) => ({ ...current, photo: t("reportLostItem.badType") }));
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setErrors((current) => ({
        ...current,
        photo: t("reportLostItem.tooLarge", {
          max: MAX_UPLOAD_BYTES / (1024 * 1024),
          size: (file.size / (1024 * 1024)).toFixed(1),
        }),
      }));
      return;
    }
    setErrors((current) => ({ ...current, photo: undefined, form: undefined }));
    setPhoto(file);
  };

  // The backend rejects a report with neither, so say so before submitting.
  const hasEnough = Boolean(photo) || Boolean(values.description.trim());

  const emailValid = useMemo(() => {
    const email = values.reporter_email.trim();
    return !email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }, [values.reporter_email]);

  const submit = async (event) => {
    event.preventDefault();
    const found = {};
    if (!hasEnough) found.form = t("reportLostItem.needPhotoOrText");
    if (!emailValid) found.reporter_email = t("reportLostItem.badEmail");
    setErrors(found);
    if (Object.keys(found).length) return;

    setSaving(true);
    setSubmitError(null);
    try {
      const response = await lostApi.report({
        photo,
        description: values.description.trim(),
        reporterName: values.reporter_name.trim(),
        reporterEmail: values.reporter_email.trim(),
        className: values.class_name,
        // datetime-local gives "YYYY-MM-DDTHH:mm", which FastAPI parses as a
        // naive datetime — correct here, since the operator means local time.
        lostAfter: values.lost_after,
      });
      const lostId = response?.data?.lost_id;
      toast.success(t("reportLostItem.reportFiledRankingTheFound"));
      navigate(lostId ? `/lost-items/${lostId}` : "/lost-items");
    } catch (err) {
      setSubmitError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box>
      <Button startIcon={<ArrowBackIcon />} onClick={() => navigate("/lost-items")} sx={{ mb: 2 }}>
        {t("reportLostItem.allReports")}
      </Button>

      <PageHeader
        title={t("reportLostItem.reportALostItem")}
        subtitle={t("reportLostItem.candidatesAreMatchedOnObject")}
      />

      <Box component="form" onSubmit={submit} noValidate>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, lg: 5 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>
                  {t("reportLostItem.photo")}
                </Typography>
                <ItemImage
                  src={preview}
                  alt={photo ? t("reportLostItem.previewOfName", { name: photo.name }) : t("reportLostItem.noPhotoSelected")}
                  height={260}
                  fit="contain"
                  fallbackLabel={t("reportLostItem.noPhotoSelected")}
                  sx={{ borderRadius: 1, mb: 2 }}
                />
                <Button
                  component="label"
                  variant="outlined"
                  fullWidth
                  startIcon={<PhotoCameraIcon />}
                >
                  {photo ? t("reportLostItem.chooseADifferentPhoto") : t("reportLostItem.chooseAPhoto")}
                  <input
                    type="file"
                    hidden
                    accept={ACCEPTED.join(",")}
                    onChange={pickPhoto}
                    aria-label={t("reportLostItem.photoOfTheLostItem")}
                  />
                </Button>
                {photo ? (
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                    sx={{ mt: 1 }}
                  >
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {photo.name}
                    </Typography>
                    <Button size="small" color="inherit" onClick={() => setPhoto(null)}>
                      {t("reportLostItem.remove")}
                    </Button>
                  </Stack>
                ) : null}
                {errors.photo ? (
                  <Typography variant="caption" color="error" sx={{ mt: 1, display: "block" }}>
                    {errors.photo}
                  </Typography>
                ) : null}
              </CardContent>
            </Card>
          </Grid>

          <Grid size={{ xs: 12, lg: 7 }}>
            <Card>
              <CardContent>
                <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 2 }}>
                  {t("reportLostItem.details")}
                </Typography>
                <Stack spacing={2.5}>
                  <TextField
                    label={t("reportLostItem.description")}
                    value={values.description}
                    onChange={setField("description")}
                    fullWidth
                    multiline
                    minRows={2}
                    placeholder={t("reportLostItem.blackLeatherBagWithA")}
                    helperText={t("reportLostItem.colourMaterialAndDistinguishingMarks")}
                  />
                  <TextField
                    select
                    label={t("reportLostItem.objectType")}
                    value={values.class_name}
                    onChange={setField("class_name")}
                    fullWidth
                    helperText={t("reportLostItem.narrowsTheSearchAndAdds")}
                  >
                    <MenuItem value="">{t("reportLostItem.notSure")}</MenuItem>
                    {OBJECT_CLASSES.map((value) => (
                      <MenuItem key={value} value={value}>
                        {titleCase(value)}
                      </MenuItem>
                    ))}
                  </TextField>

                  <Divider />

                  <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                    <TextField
                      label={t("reportLostItem.yourName")}
                      value={values.reporter_name}
                      onChange={setField("reporter_name")}
                      fullWidth
                    />
                    <TextField
                      label={t("reportLostItem.email")}
                      type="email"
                      value={values.reporter_email}
                      onChange={setField("reporter_email")}
                      error={Boolean(errors.reporter_email)}
                      helperText={errors.reporter_email || t("reportLostItem.soWeCanTellYou")}
                      fullWidth
                    />
                  </Stack>

                  <TextField
                    label={t("reportLostItem.lostAfter")}
                    type="datetime-local"
                    value={values.lost_after}
                    onChange={setField("lost_after")}
                    fullWidth
                    slotProps={{ inputLabel: { shrink: true } }}
                    helperText={t("reportLostItem.optionalItemsFoundBeforeThis")}
                  />
                </Stack>
              </CardContent>
            </Card>
          </Grid>

          <Grid size={12}>
            {errors.form ? (
              <Alert severity="warning" sx={{ mb: 2 }}>
                {errors.form}
              </Alert>
            ) : null}
            {submitError ? (
              <Alert severity="error" sx={{ mb: 2 }}>
                {submitError}
              </Alert>
            ) : null}
            <Stack direction="row" spacing={1}>
              <Button type="submit" variant="contained" disabled={saving || !hasEnough}>
                {saving ? t("reportLostItem.filing") : t("reportLostItem.fileReport")}
              </Button>
              <Button color="inherit" disabled={saving} onClick={() => navigate("/lost-items")}>
                {t("reportLostItem.cancel")}
              </Button>
            </Stack>
          </Grid>
        </Grid>
      </Box>
    </Box>
  );
}
