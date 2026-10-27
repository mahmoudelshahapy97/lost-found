import { useMemo } from "react";
import { PlatformProvider } from "@insighteye/ui";
import { audit, auth as authApi, cameras, health, notifications, system } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { getAccessToken } from "../auth/tokenStore";
import { useWorkspace } from "../workspace/WorkspaceContext";

export const APP_KEY = "lost-found";

/**
 * This console's side of the @insighteye/ui platform adapter (see
 * packages/insighteye-ui/README.md): how the shared shell, auth pages,
 * notifications, live wall and audit log reach this backend.
 */
export function PlatformBridge({ children }) {
  const authState = useAuth();
  const workspace = useWorkspace();

  const value = useMemo(
    () => ({
      appKey: APP_KEY,
      auth: {
        user: authState.user,
        status: authState.status,
        login: authState.login,
        logout: authState.logout,
        refreshProfile: authState.refreshProfile,
        // Permissions are the global role floor: viewer < operator < admin.
        can: (perm) => authState.hasRole(perm),
        getAccessToken,
      },
      workspace: authState.user ? workspace : null,
      emailAlerts: {
        eligible: (user, options) => authState.hasRole(options.alert_email_min_role || "operator"),
        enabled: (user) => user?.alert_emails !== false,
        set: (on) => authApi.updateMe({ alert_emails: on }),
      },
      api: {
        health: (opts) => health.live(opts),
        authOptions: (opts) =>
          authApi.options(opts).then((options) => ({ ...options, notify_email: options.alert_emails })),
        changePassword: authApi.changePassword,
        forgotPassword: authApi.forgotPassword,
        resetPassword: authApi.resetPassword,
        notifications,
        audit,
        cameras: {
          // The live wall wants each camera with whether its worker is up.
          list: async (opts) => {
            const [list, workers] = await Promise.all([
              cameras.list(undefined, opts),
              system.workers(opts).catch(() => null),
            ]);
            const running = new Set(
              (workers?.data?.workers || []).filter((w) => w.running).map((w) => String(w.camera_id))
            );
            return (list || []).map((c) => ({
              camera_id: c.camera_id,
              name: c.name,
              location: c.location,
              running: c.enabled && running.has(String(c.camera_id)),
            }));
          },
          snapshotUrl: cameras.snapshotUrl,
          probe: cameras.probe,
          probeAll: cameras.probeAll,
        },
      },
    }),
    [authState, workspace]
  );

  return <PlatformProvider value={value}>{children}</PlatformProvider>;
}

export default PlatformBridge;
