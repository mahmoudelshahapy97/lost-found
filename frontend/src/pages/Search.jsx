import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import ImageSearchIcon from "@mui/icons-material/ImageSearch";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";
import SearchIcon from "@mui/icons-material/Search";

import ItemImage from "../components/ItemImage";
import PageHeader from "../components/PageHeader";
import { EmptyState } from "../components/DataStates";
import { FoundStatusChip } from "../components/StatusChips";
import { errorMessage } from "../api/client";
import { foundItems, search as searchApi } from "../api/endpoints";
import { DEFAULT_MIN_SIMILARITY, OBJECT_CLASSES } from "../utils/constants";
import { formatScore, fromNow, titleCase } from "../utils/format";

const ACCEPTED = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/bmp"];

/**
 * Ad-hoc search: "does this bag look familiar?" without filing a report.
 * Nothing is stored, which is the difference between this page and the report
 * form — no lost_item row, no persisted shortlist.
 */
export default function Search() {
  const [tab, setTab] = useState("text");
  const [description, setDescription] = useState("");
  const [className, setClassName] = useState("");
  const [minSimilarity, setMinSimilarity] = useState(DEFAULT_MIN_SIMILARITY);
  const [photo, setPhoto] = useState(null);
  const [preview, setPreview] = useState(null);

  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return undefined;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const pickPhoto = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!ACCEPTED.includes(file.type)) {
      setError("Must be a JPEG, PNG, WebP or BMP image.");
      return;
    }
    setError(null);
    setPhoto(file);
  };

  const canSearch = tab === "text" ? description.trim().length >= 2 : Boolean(photo);

  const run = async (event) => {
    event?.preventDefault();
    if (!canSearch) return;

    setSearching(true);
    setError(null);
    try {
      const response =
        tab === "text"
          ? await searchApi.byText({
              description: description.trim(),
              class_name: className || null,
              min_similarity: minSimilarity,
            })
          : await searchApi.byImage({
              photo,
              description: description.trim(),
              className,
              minSimilarity,
            });
      setResults(response);
    } catch (err) {
      setError(errorMessage(err));
      setResults(null);
    } finally {
      setSearching(false);
    }
  };

  const matches = results?.matches || [];

  return (
    <Box>
      <PageHeader
        title="Search the found gallery"
        subtitle="CLIP puts a photo and a phrase in the same vector space, so either can be compared against the crops the cameras harvested. Nothing here is stored."
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 4 }}>
          <Card component="form" onSubmit={run}>
            <Tabs
              value={tab}
              onChange={(_, next) => setTab(next)}
              variant="fullWidth"
              sx={{ borderBottom: 1, borderColor: "divider" }}
            >
              <Tab value="text" label="By description" icon={<SearchIcon />} iconPosition="start" />
              <Tab value="image" label="By photo" icon={<PhotoCameraIcon />} iconPosition="start" />
            </Tabs>

            <CardContent>
              <Stack spacing={2.5}>
                {tab === "image" ? (
                  <>
                    <ItemImage
                      src={preview}
                      alt={photo ? `Preview of ${photo.name}` : "No photo selected"}
                      height={200}
                      fit="contain"
                      fallbackLabel="No photo selected"
                      sx={{ borderRadius: 1 }}
                    />
                    <Button component="label" variant="outlined" startIcon={<PhotoCameraIcon />}>
                      {photo ? "Choose a different photo" : "Choose a photo"}
                      <input
                        type="file"
                        hidden
                        accept={ACCEPTED.join(",")}
                        onChange={pickPhoto}
                        aria-label="Photo to search with"
                      />
                    </Button>
                  </>
                ) : null}

                <TextField
                  label={tab === "text" ? "Description" : "Description (optional)"}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  fullWidth
                  multiline
                  minRows={2}
                  placeholder="black leather backpack"
                  required={tab === "text"}
                  helperText={
                    tab === "text"
                      ? "At least two characters."
                      : "Blended with the photo at the weight MATCH_TEXT_WEIGHT sets."
                  }
                />

                <TextField
                  select
                  label="Object type"
                  value={className}
                  onChange={(event) => setClassName(event.target.value)}
                  fullWidth
                >
                  <MenuItem value="">Any</MenuItem>
                  {OBJECT_CLASSES.map((value) => (
                    <MenuItem key={value} value={value}>
                      {titleCase(value)}
                    </MenuItem>
                  ))}
                </TextField>

                <Box>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    Minimum similarity — {formatScore(minSimilarity)}
                  </Typography>
                  <Slider
                    value={minSimilarity}
                    onChange={(_, value) => setMinSimilarity(value)}
                    min={0}
                    max={1}
                    step={0.01}
                    valueLabelDisplay="auto"
                    valueLabelFormat={(value) => formatScore(value, 0)}
                    aria-label="Minimum similarity"
                  />
                  <Typography variant="caption" color="text.disabled">
                    Lower it to see more, weaker candidates.
                  </Typography>
                </Box>

                <Button
                  type="submit"
                  variant="contained"
                  startIcon={<SearchIcon />}
                  disabled={!canSearch || searching}
                >
                  {searching ? "Searching…" : "Search"}
                </Button>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 8 }}>
          {error ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          ) : null}

          {results ? (
            <Card sx={{ px: 2.5, py: 2, mb: 2 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {results.count} {results.count === 1 ? "candidate" : "candidates"}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Unclaimed items only, ranked by cosine similarity and reranked with class and colour
                bonuses.
              </Typography>
            </Card>
          ) : null}

          {matches.length ? (
            <Grid container spacing={2}>
              {matches.map((match) => (
                <Grid key={match.found_id} size={{ xs: 12, sm: 6, lg: 4 }}>
                  <Card sx={{ height: "100%" }}>
                    <ItemImage
                      src={foundItems.cropUrl(match.found_id)}
                      alt={`Found ${match.class_name}`}
                      height={170}
                      fallbackLabel="No crop stored"
                    />
                    <CardContent>
                      <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                        sx={{ mb: 1 }}
                      >
                        <Typography variant="subtitle2">{titleCase(match.class_name)}</Typography>
                        <Tooltip title={`Raw score ${Number(match.score).toFixed(4)}`}>
                          <Chip
                            size="small"
                            color={match.score >= 0.8 ? "success" : "default"}
                            label={formatScore(match.score)}
                          />
                        </Tooltip>
                      </Stack>
                      <Divider sx={{ mb: 1 }} />
                      <Typography variant="caption" color="text.secondary" display="block">
                        Image {formatScore(match.image_similarity)}
                        {match.text_similarity !== null && match.text_similarity !== undefined
                          ? ` · text ${formatScore(match.text_similarity)}`
                          : ""}
                      </Typography>
                      <Typography variant="caption" color="text.disabled" display="block">
                        {match.camera_name || "Unknown camera"} · {fromNow(match.found_at)}
                      </Typography>
                      <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                        {match.dominant_color ? (
                          <Chip
                            size="small"
                            variant="outlined"
                            label={titleCase(match.dominant_color)}
                          />
                        ) : null}
                        <FoundStatusChip status={match.status} />
                      </Stack>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          ) : (
            <Card>
              <EmptyState
                title={results ? "Nothing cleared the bar" : "No search yet"}
                description={
                  results
                    ? "Try lowering the minimum similarity, dropping the object-type filter, or describing the item differently."
                    : "Describe the item, or upload a photo of one like it, and the gallery is ranked against it."
                }
                icon={<ImageSearchIcon fontSize="inherit" />}
                action={
                  results ? (
                    <Button component={RouterLink} to="/found-items" variant="outlined">
                      Browse the whole gallery
                    </Button>
                  ) : null
                }
              />
            </Card>
          )}
        </Grid>
      </Grid>
    </Box>
  );
}
