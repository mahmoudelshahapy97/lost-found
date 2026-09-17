import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "../layouts/AppLayout";
import AuthLayout from "../layouts/AuthLayout";
import { Loading } from "../components/DataStates";
import { RequireAuth } from "./RequireAuth";

// Code-split per route: the dashboard is the landing screen and has no business
// downloading the report form and the search page before it can paint.
const Login = lazy(() => import("../pages/Login"));
const Dashboard = lazy(() => import("../pages/Dashboard"));
const CameraList = lazy(() => import("../pages/cameras/CameraList"));
const CameraForm = lazy(() => import("../pages/cameras/CameraForm"));
const CameraDetail = lazy(() => import("../pages/cameras/CameraDetail"));
const Events = lazy(() => import("../pages/Events"));
const EventDetail = lazy(() => import("../pages/EventDetail"));
const LostItems = lazy(() => import("../pages/LostItems"));
const LostItemDetail = lazy(() => import("../pages/LostItemDetail"));
const ReportLostItem = lazy(() => import("../pages/ReportLostItem"));
const FoundItems = lazy(() => import("../pages/FoundItems"));
const Search = lazy(() => import("../pages/Search"));
const SystemStatus = lazy(() => import("../pages/SystemStatus"));
const Users = lazy(() => import("../pages/admin/Users"));
const NotFound = lazy(() => import("../pages/NotFound"));

export function AppRouter({ mode, onToggleMode }) {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading label="Loading…" height="60vh" />}>
        <Routes>
          <Route element={<AuthLayout />}>
            <Route path="/login" element={<Login />} />
          </Route>

          <Route
            element={
              <RequireAuth>
                <AppLayout mode={mode} onToggleMode={onToggleMode} />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Dashboard />} />

            <Route path="/cameras">
              <Route index element={<CameraList />} />
              <Route
                path="new"
                element={
                  <RequireAuth minimum="admin">
                    <CameraForm />
                  </RequireAuth>
                }
              />
              <Route path=":cameraId" element={<CameraDetail />} />
              <Route
                path=":cameraId/edit"
                element={
                  <RequireAuth minimum="admin">
                    <CameraForm />
                  </RequireAuth>
                }
              />
            </Route>

            <Route path="/events">
              <Route index element={<Events />} />
              <Route path=":eventId" element={<EventDetail />} />
            </Route>

            <Route path="/lost-items">
              <Route index element={<LostItems />} />
              {/* Before :lostId, or "new" would be read as an id. */}
              <Route
                path="new"
                element={
                  <RequireAuth minimum="operator">
                    <ReportLostItem />
                  </RequireAuth>
                }
              />
              <Route path=":lostId" element={<LostItemDetail />} />
            </Route>

            <Route path="/found-items" element={<FoundItems />} />
            <Route path="/search" element={<Search />} />
            <Route path="/system" element={<SystemStatus />} />

            <Route
              path="/users"
              element={
                <RequireAuth minimum="admin">
                  <Users />
                </RequireAuth>
              }
            />

            {/* The API calls them "events"; operators call them alerts. Both work. */}
            <Route path="/alerts" element={<Navigate to="/events" replace />} />

            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default AppRouter;
