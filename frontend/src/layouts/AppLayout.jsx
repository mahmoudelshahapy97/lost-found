import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import Alert from "@mui/material/Alert";
import AppBar from "@mui/material/AppBar";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import ListSubheader from "@mui/material/ListSubheader";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import DashboardIcon from "@mui/icons-material/SpaceDashboard";
import VideocamIcon from "@mui/icons-material/Videocam";
import NotificationsIcon from "@mui/icons-material/NotificationsActive";
import InsightsIcon from "@mui/icons-material/Insights";
import ReportProblemIcon from "@mui/icons-material/ReportProblem";
import Inventory2Icon from "@mui/icons-material/Inventory2";
import ImageSearchIcon from "@mui/icons-material/ImageSearch";
import TuneIcon from "@mui/icons-material/Tune";
import GroupIcon from "@mui/icons-material/Group";
import WorkspacesIcon from "@mui/icons-material/Workspaces";
import MenuIcon from "@mui/icons-material/Menu";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import MenuBookIcon from "@mui/icons-material/MenuBook";

import { events, health } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAuth } from "../auth/AuthContext";
import UserMenu from "../components/UserMenu";
import WorkspaceSwitcher from "../components/WorkspaceSwitcher";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import { useWorkspace } from "../workspace/WorkspaceContext";
import { POLL_INTERVAL_MS } from "../utils/constants";
import { titleCase } from "../utils/format";

const DRAWER_WIDTH = 248;

/**
 * Grouped by how the work actually flows: watch the cameras, triage what they
 * raise, then take reports and reunite items.
 *
 * `minimum` mirrors the role floor enforced server-side for the same action
 * (see backend/app/api/deps.py and the guards on each router) -- hiding an
 * item a viewer cannot use keeps the console honest, but the API check is the
 * real one.
 */
const NAV_SECTIONS = [
  {
    heading: "Monitor",
    items: [
      { to: "/", label: "Dashboard", icon: <DashboardIcon />, end: true, minimum: "viewer" },
      { to: "/cameras", label: "Cameras", icon: <VideocamIcon />, minimum: "viewer" },
      {
        to: "/events",
        label: "Alerts",
        icon: <NotificationsIcon />,
        minimum: "viewer",
        // Shows the open-alert count from useAlertWatch.
        badge: "openAlerts",
      },
      { to: "/analytics", label: "Analytics", icon: <InsightsIcon />, minimum: "viewer" },
    ],
  },
  {
    heading: "Lost & Found",
    items: [
      { to: "/lost-items", label: "Lost reports", icon: <ReportProblemIcon />, minimum: "viewer" },
      { to: "/found-items", label: "Found gallery", icon: <Inventory2Icon />, minimum: "viewer" },
      { to: "/search", label: "Search", icon: <ImageSearchIcon />, minimum: "viewer" },
    ],
  },
  {
    heading: "System",
    items: [
      { to: "/system", label: "Workers & config", icon: <TuneIcon />, minimum: "viewer" },
      { to: "/workspaces", label: "Workspaces", icon: <WorkspacesIcon />, minimum: "admin" },
      { to: "/users", label: "Users", icon: <GroupIcon />, minimum: "admin" },
    ],
  },
];

const NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items);

/**
 * Backend reachability, shown in the bar so a dead API is never a mystery.
 *
 * Three states, because they call for different reactions: healthy is
 * everything up; degraded is the API answering while Postgres is not, which
 * still serves cached routes but cannot record an event; unreachable means the
 * proxy has nothing to talk to.
 */
function BackendStatus() {
  const { data, error } = usePolling(({ signal }) => health.live({ signal }), {
    intervalMs: 15000,
  });

  if (error) {
    return <Chip size="small" color="error" label="API unreachable" variant="filled" />;
  }
  if (!data) return <Chip size="small" label="Checking…" variant="outlined" />;

  const degraded = data.status !== "healthy";
  const workers = data.workers;
  return (
    <Tooltip
      title={
        `Database: ${data.db_connection_ok ? "connected" : "unreachable"} · ` +
        `workers running: ${workers?.running ?? 0}/${workers?.total ?? 0}` +
        (data.version ? ` · API v${data.version}` : "")
      }
    >
      <Chip
        size="small"
        color={degraded ? "warning" : "success"}
        variant={degraded ? "filled" : "outlined"}
        label={degraded ? `API ${data.status}` : "API ok"}
      />
    </Tooltip>
  );
}

/**
 * Watches the active workspace's alerts from anywhere in the console: the open
 * count for the Alerts menu entry, and each alert that arrives while the
 * console is open, for the pop-up. The first answer after load or a workspace
 * switch is only the baseline, so old alerts never pop up.
 */
function useAlertWatch(workspaceId) {
  const seenRef = useRef({ workspaceId: null, lastAt: null });
  const [arrived, setArrived] = useState(null);

  // Each answer is tagged with the workspace it was asked for: right after a
  // switch the previous workspace's answer is still held, and must not become
  // the new baseline.
  const stats = usePolling(
    ({ signal }) =>
      events.stats(undefined, { signal }).then((body) => ({ ...body.data, workspaceId })),
    { intervalMs: POLL_INTERVAL_MS * 2, enabled: Boolean(workspaceId), deps: [workspaceId] }
  );
  const current = stats.data?.workspaceId === workspaceId ? stats.data : null;

  useEffect(() => {
    if (!current || !workspaceId) return;
    const seen = seenRef.current;
    const lastAt = current.last_event_at || null;
    if (seen.workspaceId !== workspaceId) {
      seenRef.current = { workspaceId, lastAt };
      setArrived(null);
      return;
    }
    if (!lastAt || (seen.lastAt && new Date(lastAt) <= new Date(seen.lastAt))) return;
    const since = seen.lastAt;
    seenRef.current = { workspaceId, lastAt };
    events
      .list({ per_page: 5 })
      .then((page) => {
        const fresh = (page?.events || []).filter(
          (event) => !since || new Date(event.abandoned_at) > new Date(since)
        );
        if (fresh.length) setArrived({ event: fresh[0], count: fresh.length, key: lastAt });
      })
      .catch(() => {});
  }, [current, workspaceId]);

  return {
    openAlerts: current?.open ?? 0,
    arrived,
    dismiss: () => setArrived(null),
  };
}

function NewAlertSnackbar({ arrived, onClose }) {
  const navigate = useNavigate();
  const event = arrived?.event;
  const more = arrived && arrived.count > 1 ? ` (+${arrived.count - 1} more)` : "";
  return (
    <Snackbar
      key={arrived?.key}
      open={Boolean(arrived)}
      autoHideDuration={12000}
      onClose={(_, reason) => reason !== "clickaway" && onClose()}
      anchorOrigin={{ vertical: "top", horizontal: "right" }}
      sx={{ mt: 7 }}
    >
      <Alert
        severity="warning"
        variant="filled"
        icon={<NotificationsIcon />}
        onClose={onClose}
        action={
          <Button
            color="inherit"
            size="small"
            onClick={() => {
              onClose();
              navigate(arrived.count > 1 ? "/events" : `/events/${event.event_id}`);
            }}
          >
            View
          </Button>
        }
        sx={{ alignItems: "center" }}
      >
        {event
          ? `New alert: abandoned ${titleCase(event.class_name || "item").toLowerCase()} on ${
              event.camera_name || "a camera"
            }${more}`
          : null}
      </Alert>
    </Snackbar>
  );
}

export function AppLayout({ mode, onToggleMode }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const { hasRole } = useAuth();
  const workspace = useWorkspace();
  const alerts = useAlertWatch(workspace.active?.workspace_id);

  const visibleSections = NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => hasRole(item.minimum)),
  })).filter((section) => section.items.length > 0);

  const drawer = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5 }}>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.2 }}>
            InsightEye
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Lost &amp; found detection
          </Typography>
        </Box>
      </Toolbar>
      <Divider />
      <Box sx={{ flexGrow: 1, overflowY: "auto", py: 1 }}>
        {visibleSections.map((section) => (
          <List
            key={section.heading}
            dense
            sx={{ px: 1.5 }}
            subheader={
              <ListSubheader
                disableSticky
                sx={{
                  bgcolor: "transparent",
                  lineHeight: 2.2,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  fontSize: 11,
                }}
              >
                {section.heading}
              </ListSubheader>
            }
          >
            {section.items.map((item) => (
              <ListItemButton
                key={item.to}
                component={NavLink}
                to={item.to}
                end={item.end}
                // A badge would otherwise become part of the link's name.
                aria-label={item.badge ? item.label : undefined}
                onClick={() => setMobileOpen(false)}
                sx={{
                  borderRadius: 2,
                  mb: 0.5,
                  // NavLink stamps .active on the matching route, so the
                  // highlight is the router's business rather than state we keep.
                  "&.active": {
                    bgcolor: "action.selected",
                    color: "primary.main",
                    "& .MuiListItemIcon-root": { color: "primary.main" },
                  },
                }}
              >
                <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
                <ListItemText primaryTypographyProps={{ fontWeight: 600 }} primary={item.label} />
                {item.badge && alerts[item.badge] ? (
                  <Badge
                    color="error"
                    max={99}
                    badgeContent={alerts[item.badge]}
                    // The link keeps its plain label as its name; the count is a hint.
                    aria-hidden
                    title={`${alerts[item.badge]} open`}
                    sx={{ mr: 1.5, "& .MuiBadge-badge": { position: "static", transform: "none" } }}
                  />
                ) : null}
              </ListItemButton>
            ))}
          </List>
        ))}
      </Box>
      <Divider />
      <Box sx={{ p: 1.5 }}>
        <ListItemButton
          component="a"
          href="/docs"
          target="_blank"
          rel="noreferrer"
          sx={{ borderRadius: 2 }}
        >
          <ListItemIcon sx={{ minWidth: 40 }}>
            <MenuBookIcon />
          </ListItemIcon>
          <ListItemText
            primary="API docs"
            secondary="FastAPI /docs"
            primaryTypographyProps={{ fontWeight: 600 }}
          />
        </ListItemButton>
      </Box>
    </Box>
  );

  // Longest matching prefix, so /cameras/<id> still titles as "Cameras" and
  // "/" does not match everything.
  const currentTitle =
    [...NAV_ITEMS]
      .sort((a, b) => b.to.length - a.to.length)
      .find((item) =>
        item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)
      )?.label || "Lost & found detection";

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar
        position="fixed"
        color="default"
        elevation={0}
        sx={{
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          ml: { md: `${DRAWER_WIDTH}px` },
          borderBottom: 1,
          borderColor: "divider",
          backdropFilter: "blur(8px)",
          bgcolor: (t) =>
            t.palette.mode === "dark" ? "rgba(11,18,32,0.82)" : "rgba(255,255,255,0.86)",
        }}
      >
        <Toolbar>
          <IconButton
            edge="start"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            sx={{ mr: 2, display: { md: "none" } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {currentTitle}
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <WorkspaceSwitcher />
            <BackendStatus />
            <Tooltip title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
              <IconButton onClick={onToggleMode} aria-label="Toggle colour mode">
                {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
              </IconButton>
            </Tooltip>
            <UserMenu />
          </Stack>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
        <Drawer
          variant={isDesktop ? "permanent" : "temporary"}
          open={isDesktop || mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
              borderRight: 1,
              borderColor: "divider",
              backgroundImage: "none",
            },
          }}
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          // A flex child otherwise grows to its widest descendant, so one wide
          // table pushes the whole page sideways on a phone instead of
          // scrolling inside its own container.
          minWidth: 0,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          px: { xs: 2, md: 3 },
          pb: 4,
        }}
      >
        <Toolbar />
        <Box sx={{ pt: 3 }}>
          {!workspace.ready ? (
            <Loading label="Loading workspaces…" />
          ) : workspace.active ? (
            // Keyed on the workspace, so switching reloads the open page.
            <Outlet key={workspace.active.workspace_id} />
          ) : workspace.error ? (
            <ErrorState error={workspace.error} onRetry={workspace.reload} />
          ) : (
            <EmptyState
              title="You are not in any workspace yet"
              description="Everything here belongs to a workspace. Ask an admin to add your account to one."
              icon={<WorkspacesIcon fontSize="inherit" />}
            />
          )}
        </Box>
      </Box>
      <NewAlertSnackbar arrived={alerts.arrived} onClose={alerts.dismiss} />
    </Box>
  );
}

export default AppLayout;
