import { useCallback, useEffect, useState } from "react";

import {
  ArrowUpRight,
  Info,
  LayoutDashboard,
  LayoutGrid,
  LogOut,
  PanelsTopLeft,
  UserRound,
  Users,
} from "lucide-react";

import { UsersPage } from "./pages/UsersPage";
import { UserDetailPage } from "./pages/UserDetailPage";
import { ATurnosPage } from "./pages/ATurnosPage";

import "./App.css";

const BACKEND = "http://127.0.0.1:8001";
const ACCOUNT_TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const ACCOUNT_DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

type Application = {
  code: string;
  display_name: string;
  launch_url: string | null;
};

type RegisteredApplication = Application & {
  id: string;
  oidc_client_id: string | null;
  is_enabled: boolean;
};

type PortalSession = {
  user_id: string;
  user_display_name?: string;
  applications: Application[];
  is_admin: boolean;
};

type Status = "loading" | "authenticated" | "error";

type View = "workspace" | "users" | "applications" | "aturnos";

function isApplication(value: unknown): value is Application {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const app = value as Record<string, unknown>;

  return (
    typeof app.code === "string" &&
    typeof app.display_name === "string" &&
    (typeof app.launch_url === "string" || app.launch_url === null)
  );
}

function isRegisteredApplication(
  value: unknown,
): value is RegisteredApplication {
  if (!isApplication(value)) {
    return false;
  }

  return (
    "id" in value &&
    typeof value.id === "string" &&
    "oidc_client_id" in value &&
    (
      typeof value.oidc_client_id === "string" ||
      value.oidc_client_id === null
    ) &&
    "is_enabled" in value &&
    typeof value.is_enabled === "boolean"
  );
}

function isPortalSession(value: unknown): value is PortalSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const data = value as Record<string, unknown>;

  return (
    typeof data.user_id === "string" &&
    (data.user_display_name === undefined ||
      typeof data.user_display_name === "string") &&
    typeof data.is_admin === "boolean" &&
    Array.isArray(data.applications) &&
    data.applications.every(isApplication)
  );
}

function safeLaunchUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);

    return ["http:", "https:"].includes(url.protocol)
      ? url.href
      : null;
  } catch {
    return null;
  }
}

function ApplicationCard({ app }: { app: Application }) {
  const url = safeLaunchUrl(app.launch_url);
  const isMySim = app.code === "mysim_dashboard";

  return (
    <article className="application-card">
      <div className="application-heading">
        <div className="application-icon">
          {isMySim ? (
            <LayoutDashboard size={22} aria-hidden="true" />
          ) : (
            <PanelsTopLeft size={22} aria-hidden="true" />
          )}
        </div>

        <div>
          <h2>{app.display_name}</h2>

          <span className="application-category">
            {isMySim
              ? "Maintenance & Support"
              : "Internal application"}
          </span>
        </div>
      </div>

      <p className="application-description">
        {isMySim
          ? "Jobs, DRs, actions, tasks and simulator availability."
          : "Access your application workspace."}
      </p>

      <div className="application-footer">
        <span className="access-status">Access granted</span>

        {url ? (
          <a href={url} className="open-application">
            Open
            <ArrowUpRight size={15} aria-hidden="true" />
          </a>
        ) : (
          <span className="unavailable-link">Not configured</span>
        )}
      </div>
    </article>
  );
}

function AccountClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let timer: number;

    function updateClock() {
      const current = new Date();
      setNow(current);
      timer = window.setTimeout(
        updateClock,
        60_000 - (current.getTime() % 60_000),
      );
    }

    updateClock();
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <time className="account-clock" dateTime={now.toISOString()}>
      <span className="account-clock-time">{ACCOUNT_TIME_FORMAT.format(now)}</span>
      <span className="account-clock-date">{ACCOUNT_DATE_FORMAT.format(now)}</span>
    </time>
  );
}

export default function App() {
  const [status, setStatus] = useState<Status>("loading");
  const [session, setSession] = useState<PortalSession | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<View>("workspace");

  const [selectedUserId, setSelectedUserId] = useState<string | null>(
    null,
  );

  const [applications, setApplications] = useState<
    RegisteredApplication[]
  >([]);

  const [catalogStatus, setCatalogStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");

  const handleSessionExpired = useCallback(() => {
    setSession(null);
    setStatus("loading");
    window.location.replace(`${BACKEND}/auth/login`);
  }, []);

  const handleManageUser = useCallback((userId: string) => {
    setSelectedUserId(userId);
    setView("users");
  }, []);

  const handleBackToUsers = useCallback(() => {
    setSelectedUserId(null);
    setView("users");
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(
      () => controller.abort(),
      10000,
    );

    async function loadSession() {
      setStatus("loading");

      try {
        const response = await fetch("/api/v1/portal/me", {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });

        if (disposed) return;

        if (response.status === 401) {
          handleSessionExpired();
          return;
        }

        if (!response.ok) {
          throw new Error("Session request failed");
        }

        const data: unknown = await response.json();

        if (!isPortalSession(data)) {
          throw new Error("Invalid session response");
        }

        if (!disposed) {
          setSession(data);
          setStatus("authenticated");

          if (!data.is_admin) {
            setView("workspace");
            setSelectedUserId(null);
          }
        }
      } catch {
        if (!disposed) {
          setStatus("error");
        }
      } finally {
        window.clearTimeout(timeout);
      }
    }

    void loadSession();

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt, handleSessionExpired]);

  useEffect(() => {
    if (
      status !== "authenticated" ||
      !session?.is_admin ||
      view !== "applications"
    ) {
      return;
    }

    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(
      () => controller.abort(),
      10000,
    );

    async function loadApplications() {
      setCatalogStatus("loading");

      try {
        const response = await fetch("/api/v1/admin/applications", {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });

        if (disposed) return;

        if (response.status === 401) {
          handleSessionExpired();
          return;
        }

        if (!response.ok) {
          throw new Error("Applications request failed");
        }

        const data: unknown = await response.json();

        if (
          !Array.isArray(data) ||
          !data.every(isRegisteredApplication)
        ) {
          throw new Error("Invalid applications response");
        }

        if (!disposed) {
          setApplications(data);
          setCatalogStatus("ready");
        }
      } catch {
        if (!disposed) {
          setCatalogStatus("error");
        }
      } finally {
        window.clearTimeout(timeout);
      }
    }

    void loadApplications();

    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [view, status, session, attempt, handleSessionExpired]);

  const signedIn = status === "authenticated" && session !== null;

  const pageTitle =
    view === "workspace"
      ? "My applications"
      : view === "users"
        ? selectedUserId
          ? "User details"
          : "Users"
        : view === "aturnos"
          ? "Import from aTurnos"
          : "Applications";

  return (
    <div className="amh">
      <header className="amh-header">
        <a className="amh-brand" href="/" aria-label="AMH home">
          <img src="/brand/AIRBUS_White_UI.svg" alt="Airbus" />

          <span className="brand-divider" />

          <span className="brand-title">
            AMH
            <small>
              <span className="brand-initial">A</span>ccess{" "}
              <span className="brand-initial">M</span>anagement{" "}
              <span className="brand-initial">H</span>ub
            </small>
          </span>
        </a>

        {signedIn && (
          <div className="account-area">
            <span className="account-avatar">
              <UserRound size={17} aria-hidden="true" />
            </span>

            <div className="account-identity">
              <span className="account-label">
                <span className="account-name" title={session.user_display_name}>
                  {session.user_display_name || "Account"}
                </span>
                <small>
                  {session.is_admin ? "Administrator" : "Portal user"}
                </small>
              </span>
              <AccountClock />
            </div>

            <form method="post" action={`${BACKEND}/auth/logout`}>
              <button
                className="logout-button"
                type="submit"
                aria-label="Sign out"
                title="Sign out"
              >
                <LogOut size={18} aria-hidden="true" />
              </button>
            </form>
          </div>
        )}
      </header>

      <div className="amh-shell">
        {signedIn && (
          <aside className="amh-sidebar">
            <nav aria-label="Main navigation">
              <p className="navigation-label">WORKSPACE</p>

              <button
                type="button"
                className={`navigation-item ${
                  view === "workspace" ? "selected" : ""
                }`}
                onClick={() => {
                  setSelectedUserId(null);
                  setView("workspace");
                }}
                aria-current={
                  view === "workspace" ? "page" : undefined
                }
              >
                <LayoutGrid size={18} aria-hidden="true" />
                My applications
              </button>

              {session.is_admin && (
                <>
                  <p className="navigation-label administration">
                    ADMINISTRATION
                  </p>

                  <button
                    type="button"
                    className={`navigation-item ${
                      view === "users" ? "selected" : ""
                    }`}
                    onClick={handleBackToUsers}
                    aria-current={
                      view === "users" ? "page" : undefined
                    }
                  >
                    <Users size={18} aria-hidden="true" />
                    Users
                  </button>

                  <button
                    type="button"
                    className={`navigation-item ${
                      view === "applications" ? "selected" : ""
                    }`}
                    onClick={() => {
                      setSelectedUserId(null);
                      setView("applications");
                    }}
                    aria-current={
                      view === "applications" ? "page" : undefined
                    }
                  >
                    <PanelsTopLeft size={18} aria-hidden="true" />
                    Applications
                  </button>

                  <button
                    type="button"
                    className={`navigation-item ${
                      view === "aturnos" ? "selected" : ""
                    }`}
                    onClick={() => {
                      setSelectedUserId(null);
                      setView("aturnos");
                    }}
                    aria-current={
                      view === "aturnos" ? "page" : undefined
                    }
                  >
                    <Users size={18} aria-hidden="true" />
                    aTurnos
                  </button>
                </>
              )}
            </nav>

            <div className="sidebar-footer">
              Access Management Hub
              <br />
              Internal portal
            </div>
          </aside>
        )}

        <main className={`amh-main ${signedIn ? "" : "signed-out"}`}>
          {status === "loading" && (
            <section className="session-panel" role="status">
              <h1>Preparing your workspace</h1>
              <p>Checking your session and application access.</p>
            </section>
          )}

          {status === "error" && (
            <section className="session-panel" role="alert">
              <h1>We couldn't load your workspace</h1>
              <p>Check that AMH is available and try again.</p>

              <button
                type="button"
                className="primary-button"
                onClick={() => setAttempt((value) => value + 1)}
              >
                Try again
              </button>
            </section>
          )}

          {signedIn && (
            <>
              {(view !== "users" || selectedUserId !== null) && (
                <div className="page-heading">
                  <div>
                    <h1>{pageTitle}</h1>
                  </div>
                </div>
              )}

              {view === "workspace" && (
                <>
                  <div className="applications-grid">
                    {session.applications.map((app) => (
                      <ApplicationCard key={app.code} app={app} />
                    ))}
                  </div>

                  {session.applications.length === 0 && (
                    <div className="empty-state">
                      <h2>No applications available yet</h2>
                      <p>
                        Contact your administrator to review your access.
                      </p>
                    </div>
                  )}

                  <div className="workspace-help">
                    <Info size={15} aria-hidden="true" />
                    <span>
                      Need another application? Contact your administrator.
                    </span>
                  </div>
                </>
              )}

              {view === "users" &&
                session.is_admin &&
                (
                  selectedUserId ? (
                    <UserDetailPage
                      key={selectedUserId}
                      userId={selectedUserId}
                      onBack={handleBackToUsers}
                      onSessionExpired={handleSessionExpired}
                    />
                  ) : (
                    <UsersPage
                      onSessionExpired={handleSessionExpired}
                      onManageUser={handleManageUser}
                    />
                  )
                )}

              {view === "aturnos" && session.is_admin && (
                <ATurnosPage
                  onSessionExpired={handleSessionExpired}
                  onManageUser={handleManageUser}
                />
              )}

              {view === "applications" && session.is_admin && (
                <>
                  {catalogStatus === "loading" && (
                    <p role="status">Loading applications…</p>
                  )}

                  {catalogStatus === "error" && (
                    <div className="empty-state" role="alert">
                      <p>We couldn't load the application list.</p>

                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => setAttempt((value) => value + 1)}
                      >
                        Try again
                      </button>
                    </div>
                  )}

                  {catalogStatus === "ready" && (
                    <div className="table-container">
                      <table>
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>Code</th>
                            <th>Status</th>
                          </tr>
                        </thead>

                        <tbody>
                          {applications.map((app) => (
                            <tr key={app.id}>
                              <td>{app.display_name}</td>
                              <td>{app.code}</td>
                              <td>
                                <span
                                  className={
                                    app.is_enabled
                                      ? "enabled-status"
                                      : "disabled-status"
                                  }
                                >
                                  {app.is_enabled
                                    ? "Enabled"
                                    : "Disabled"}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}