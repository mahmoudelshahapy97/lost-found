import { NotificationsPage } from "@insighteye/ui";

/** The kinds this backend raises (app/services/notification_service.py). */
const KINDS = ["alert", "match", "camera_offline", "camera_online", "system"];

export default function Notifications() {
  return <NotificationsPage kinds={KINDS} />;
}
