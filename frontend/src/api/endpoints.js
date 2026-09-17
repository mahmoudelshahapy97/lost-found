import client, { mediaUrl } from "./client";

/**
 * One function per backend route, so no component builds a URL by hand.
 *
 * Mirrors app/api/routes/: camera_router, event_router, lostfound_router and
 * system_router. The lost-and-found router carries no prefix of its own, so its
 * paths sit directly under /api/v1.
 */

// --- health and system ----------------------------------------------------
export const health = {
  // /health is mounted on the app root, outside the versioned prefix, so it is
  // the one call that has to escape the axios baseURL.
  live: (opts) => client.get("/health", { baseURL: "", ...opts }).then((r) => r.data),
};

// --- auth -------------------------------------------------------------------
export const auth = {
  login: (username, password) =>
    client.post("/auth/login", { username, password }).then((r) => r.data),
  refresh: (refreshToken) =>
    client.post("/auth/refresh", { refresh_token: refreshToken }).then((r) => r.data),
  logout: (refreshToken) =>
    client.post("/auth/logout", { refresh_token: refreshToken }).then((r) => r.data),
  logoutAll: () => client.post("/auth/logout-all").then((r) => r.data),
  me: (opts) => client.get("/auth/me", opts).then((r) => r.data),
  changePassword: (currentPassword, newPassword) =>
    client
      .post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      })
      .then((r) => r.data),
};

// --- users (admin only) ------------------------------------------------------
export const users = {
  list: (opts) => client.get("/users", opts).then((r) => r.data),
  get: (id, opts) => client.get(`/users/${id}`, opts).then((r) => r.data),
  create: (payload) => client.post("/users", payload).then((r) => r.data),
  update: (id, payload) => client.patch(`/users/${id}`, payload).then((r) => r.data),
  resetPassword: (id, newPassword) =>
    client.post(`/users/${id}/reset-password`, { new_password: newPassword }).then((r) => r.data),
  remove: (id) => client.delete(`/users/${id}`).then((r) => r.data),
};

export const system = {
  workers: (opts) => client.get("/system/workers", opts).then((r) => r.data),
  config: (opts) => client.get("/system/config", opts).then((r) => r.data),
};

// --- cameras --------------------------------------------------------------
export const cameras = {
  list: (params, opts) => client.get("/cameras", { params, ...opts }).then((r) => r.data),
  get: (id, opts) => client.get(`/cameras/${id}`, opts).then((r) => r.data),
  create: (payload) => client.post("/cameras", payload).then((r) => r.data),
  update: (id, payload) => client.patch(`/cameras/${id}`, payload).then((r) => r.data),
  remove: (id) => client.delete(`/cameras/${id}`).then((r) => r.data),

  start: (id) => client.post(`/cameras/${id}/start`).then((r) => r.data),
  stop: (id) => client.post(`/cameras/${id}/stop`).then((r) => r.data),
  status: (id, opts) => client.get(`/cameras/${id}/status`, opts).then((r) => r.data),

  /**
   * Latest frame, as an <img> source. The timestamp is not decoration: without
   * it the browser serves the frame it already has and the view never updates.
   */
  snapshotUrl: (id, bust = Date.now()) => mediaUrl(`/cameras/${id}/snapshot`, { t: bust }),
};

// --- events ---------------------------------------------------------------
export const events = {
  list: (params, opts) => client.get("/events", { params, ...opts }).then((r) => r.data),
  get: (id, params, opts) => client.get(`/events/${id}`, { params, ...opts }).then((r) => r.data),
  stats: (params, opts) => client.get("/events/stats", { params, ...opts }).then((r) => r.data),
  setStatus: (id, status) =>
    client.patch(`/events/${id}/status`, { status }).then((r) => r.data),

  /** The annotated frame captured when the object was declared abandoned. */
  frameUrl: (id) => mediaUrl(`/events/${id}/frame`),
};

// --- lost items -----------------------------------------------------------
export const lostItems = {
  list: (params, opts) => client.get("/lost-items", { params, ...opts }).then((r) => r.data),
  get: (id, params, opts) =>
    client.get(`/lost-items/${id}`, { params, ...opts }).then((r) => r.data),
  matches: (id, params, opts) =>
    client.get(`/lost-items/${id}/matches`, { params, ...opts }).then((r) => r.data),

  /**
   * Multipart, because the photo rides along with the fields. Content-Type is
   * left unset on purpose so the browser writes the multipart boundary itself;
   * setting it by hand produces a body FastAPI cannot parse.
   */
  report: ({ photo, description, reporterName, reporterEmail, className, lostAfter }) => {
    const form = new FormData();
    if (photo) form.append("photo", photo);
    if (description) form.append("description", description);
    if (reporterName) form.append("reporter_name", reporterName);
    if (reporterEmail) form.append("reporter_email", reporterEmail);
    if (className) form.append("class_name", className);
    if (lostAfter) form.append("lost_after", lostAfter);
    return client.post("/lost-items", form).then((r) => r.data);
  },
};

// --- found items ----------------------------------------------------------
export const foundItems = {
  list: (params, opts) => client.get("/found-items", { params, ...opts }).then((r) => r.data),
  cropUrl: (id) => mediaUrl(`/found-items/${id}/crop`),
};

// --- search ---------------------------------------------------------------
export const search = {
  byText: (payload) => client.post("/search/text", payload).then((r) => r.data),
  byImage: ({ photo, description, className, topK, minSimilarity }) => {
    const form = new FormData();
    form.append("photo", photo);
    if (description) form.append("description", description);
    if (className) form.append("class_name", className);
    if (topK) form.append("top_k", String(topK));
    if (minSimilarity !== undefined && minSimilarity !== null) {
      form.append("min_similarity", String(minSimilarity));
    }
    return client.post("/search/image", form).then((r) => r.data);
  },
};

// --- matches --------------------------------------------------------------
export const matches = {
  confirm: ({ lostId, foundId, score = 1.0 }) =>
    client
      .post("/matches/confirm", { lost_id: lostId, found_id: foundId, score })
      .then((r) => r.data),
  reject: ({ lostId, foundId }) =>
    client
      .delete("/matches", { params: { lost_id: lostId, found_id: foundId } })
      .then((r) => r.data),
};

export default {
  health,
  auth,
  users,
  system,
  cameras,
  events,
  lostItems,
  foundItems,
  search,
  matches,
};
