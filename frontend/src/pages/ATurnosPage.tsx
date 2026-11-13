import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Search } from "lucide-react";
import { ATurnosHistory } from "./ATurnosHistory";


import "./ATurnosPage.css";

type UserStatus = "linked" | "new" | "inactive" | "review";
type Filter = "all" | UserStatus;

type ATurnosUser = {
  id_user: string;
  name: string;
  email: string | null;
  status: UserStatus;
  reason: string;
  amh_user_id: string | null;
  amh_primary_email: string | null;
  source_present: boolean;
};

type Preview = {
  team_id: string;
  total: number;
  source_total: number;
  missing_total: number;
  items: ATurnosUser[];
};

type SyncRun = {
  id: string;
  status: "ok" | "error";
  trigger_kind: "manual" | "system";
  started_at: string;
  finished_at: string;
  error_code: string | null;
};

type SavedSync = {
  team_id: string;
  latest_run: SyncRun | null;
  last_success: SyncRun | null;
  preview: Preview | null;
};

function isSyncRun(value: unknown): value is SyncRun {
  if (typeof value !== "object" || value === null) return false;

  const run = value as Record<string, unknown>;

  return (
    typeof run.id === "string" &&
    (run.status === "ok" || run.status === "error") &&
    (
      run.trigger_kind === "manual" ||
      run.trigger_kind === "system"
    ) &&
    typeof run.started_at === "string" &&
    typeof run.finished_at === "string" &&
    !Number.isNaN(Date.parse(run.started_at)) &&
    !Number.isNaN(Date.parse(run.finished_at)) &&
    (
      typeof run.error_code === "string" ||
      run.error_code === null
    )
  );
}

function isSavedSync(value: unknown): value is SavedSync {
  if (typeof value !== "object" || value === null) return false;

  const data = value as Record<string, unknown>;

  if (
    typeof data.team_id !== "string" ||
    !(data.latest_run === null || isSyncRun(data.latest_run)) ||
    !(data.last_success === null || isSyncRun(data.last_success)) ||
    !(data.preview === null || isPreview(data.preview))
  ) {
    return false;
  }

  if (data.last_success === null) {
    return data.preview === null;
  }

  return (
    data.last_success.status === "ok" &&
    data.preview !== null &&
    data.preview.team_id === data.team_id &&
    data.latest_run !== null
  );
}

function formatSyncDate(value: string): string {
  return new Date(value).toLocaleString();
}

type ImportResult = {
  user_id: string;
  id_aturno: string;
  id_user: string;
  username: string;
  name: string;
  surname: string;
  temporary_password: string;
};

type Props = {
  onSessionExpired: () => void;
  onManageUser: (userId: string) => void;
};

const LABELS: Record<UserStatus, string> = {
  linked: "Linked",
  new: "New",
  inactive: "Inactive",
  review: "Review",
};

function isUser(value: unknown): value is ATurnosUser {
  if (typeof value !== "object" || value === null) return false;

  const item = value as Record<string, unknown>;

  return (
    typeof item.id_user === "string" &&
    typeof item.name === "string" &&
    (typeof item.email === "string" || item.email === null) &&
    (
      item.status === "linked" ||
      item.status === "new" ||
      item.status === "inactive" ||
      item.status === "review"
    ) &&
    typeof item.reason === "string" &&
    (
      typeof item.amh_user_id === "string" ||
      item.amh_user_id === null
    ) &&
    (
      typeof item.amh_primary_email === "string" ||
      item.amh_primary_email === null
    ) &&
    typeof item.source_present === "boolean"
  );
}

function isPreview(value: unknown): value is Preview {
  if (typeof value !== "object" || value === null) return false;

  const data = value as Record<string, unknown>;

  if (
    typeof data.team_id !== "string" ||
    typeof data.total !== "number" ||
    !Number.isInteger(data.total) ||
    typeof data.source_total !== "number" ||
    !Number.isInteger(data.source_total) ||
    typeof data.missing_total !== "number" ||
    !Number.isInteger(data.missing_total) ||
    data.source_total < 0 ||
    data.missing_total < 0 ||
    !Array.isArray(data.items) ||
    !data.items.every(isUser)
  ) {
    return false;
  }

  return (
    data.total === data.items.length &&
    data.total === data.source_total + data.missing_total &&
    data.missing_total === data.items.filter(
      (item) => !item.source_present,
    ).length
  );
}

function isImportResult(value: unknown): value is ImportResult {
  if (typeof value !== "object" || value === null) return false;

  const data = value as Record<string, unknown>;

  return [
    "user_id",
    "id_aturno",
    "id_user",
    "username",
    "name",
    "surname",
    "temporary_password",
  ].every(
    (key) => typeof data[key] === "string" && data[key].length > 0,
  );
}

function errorMessage(data: unknown, fallback: string): string {
  if (
    typeof data === "object" &&
    data !== null &&
    "detail" in data &&
    typeof data.detail === "string"
  ) {
    return data.detail;
  }

  return fallback;
}

export function ATurnosPage({
  onSessionExpired,
  onManageUser,
}: Props) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  const [selected, setSelected] = useState<ATurnosUser | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const [savedSync, setSavedSync] = useState<SavedSync | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(true);
  const [savedError, setSavedError] = useState("");
  const [savedRevision, setSavedRevision] = useState(0);

  const mounted = useRef(false);
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    mounted.current = true;

    return () => {
      mounted.current = false;
      activeRequest.current?.abort();
    };
  }, []);

    useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(
      () => controller.abort(),
      10000,
    );

    async function loadSavedSync() {
      setLoadingSaved(true);
      setSavedError("");

      try {
        const response = await fetch("/api/v1/admin/aturnos/latest", {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });

        if (disposed) return;

        if (response.status === 401) {
          onSessionExpired();
          return;
        }

        const data: unknown = await response.json().catch(() => null);

        if (!response.ok) {
          throw new Error(
            errorMessage(data, "Unable to load the saved comparison."),
          );
        }

        if (!isSavedSync(data)) {
          throw new Error("Invalid saved comparison response.");
        }

        if (disposed) return;

        setSavedSync(data);
        setPreview(data.preview);
      } catch (cause) {
        if (!disposed) {
          setSavedError(
            controller.signal.aborted
              ? "Loading the saved comparison took too long."
              : cause instanceof Error
                ? cause.message
                : "Unable to load the saved comparison.",
          );
        }
      } finally {
        window.clearTimeout(timeout);

        if (!disposed) {
          setLoadingSaved(false);
        }
      }
    }

    void loadSavedSync();

    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [savedRevision, onSessionExpired]);

  async function loadPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (loading || importing || loadingSaved) return;

    const form = event.currentTarget;
    const fields = new FormData(form);

    const body = JSON.stringify({
      team_id: String(fields.get("team_id") ?? "").trim(),
    });


    const controller = new AbortController();
    activeRequest.current = controller;

    const timeout = window.setTimeout(
      () => controller.abort(),
      70000,
    );

    setLoading(true);
    setError("");
    setSelected(null);
    setImportError("");

    try {
      const response = await fetch("/api/v1/admin/aturnos/preview", {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body,
        signal: controller.signal,
      });

      if (!mounted.current) return;

      if (response.status === 401) {
        onSessionExpired();
        return;
      }

      const data: unknown = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          errorMessage(
            data,
            `Unable to query aTurnos: HTTP ${response.status}`,
          ),
        );
      }

      if (!isPreview(data)) {
        throw new Error("Invalid aTurnos response.");
      }

      if (!mounted.current) return;

      setPreview(data);
      setFilter("all");
      setSearch("");
    } catch (cause) {
      if (mounted.current) {
        setError(
          controller.signal.aborted
            ? "The request took too long. Please try again."
            : cause instanceof Error
              ? cause.message
              : "Unable to query aTurnos.",
        );
      }
    } finally {
      window.clearTimeout(timeout);

      if (activeRequest.current === controller) {
        activeRequest.current = null;
      }

      if (mounted.current) {
        setLoading(false);
        setSavedRevision((value) => value + 1);
      }
    }
  }

  async function importUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (
      importing ||
      loading ||
      loadingSaved ||
      !selected ||
      !preview
    ) {
      return;
    }

    const form = event.currentTarget;
    const fields = new FormData(form);
    const teamId = preview.team_id;
    const externalId = selected.id_user;

    const name = String(fields.get("name") ?? "").trim();
    const surname = String(fields.get("surname") ?? "").trim();

    if (!name || !surname) {
      setImportError("Enter the reviewed first name and surname.");
      return;
    }

    const body = JSON.stringify({
      team_id: teamId,
      id_user: externalId,
      name,
      surname,
    });

    setImporting(true);
    setImportError("");
    setResult(null);
    setShowPassword(false);

    try {
      // No automatic retries: a connection failure may occur
      // after the server has already created the identity.
      const response = await fetch(
        "/api/v1/admin/aturnos/import-user",
        {
          method: "POST",
          credentials: "include",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body,
        },
      );

      if (!mounted.current) return;

      if (response.status === 401) {
        onSessionExpired();
        return;
      }

      const data: unknown = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          errorMessage(
            data,
            `Unable to confirm the import: HTTP ${response.status}`,
          ),
        );
      }

      if (
        !isImportResult(data) ||
        data.id_aturno !== teamId ||
        data.id_user !== externalId
      ) {
        throw new Error(
          "The server response could not be verified. " +
          "Query aTurnos again before retrying.",
        );
      }

      if (!mounted.current) return;

      setResult(data);
      setSelected(null);

      setPreview((current) => {
        if (!current || current.team_id !== teamId) return current;

        return {
          ...current,
          items: current.items.map((user) =>
            user.id_user === externalId
              ? {
                  ...user,
                  status: "linked",
                  reason: "Identity created and linked with AMH",
                  amh_user_id: data.user_id,
                  amh_primary_email: user.email,
                }
              : user,
          ),
        };
      });
    } catch (cause) {
      if (mounted.current) {
        setImportError(
          (
            cause instanceof Error
              ? cause.message
              : "Unable to confirm the import."
          ) +
          " If the result is uncertain, query aTurnos again " +
          "and check Keycloak before retrying.",
        );
      }
    } finally {
      if (mounted.current) {
        setImporting(false);
      }
    }
  }

  function selectUser(user: ATurnosUser) {
    if (loading || importing || loadingSaved || result) return;

    setSelected(user);
    setImportError("");
  }

  const query = search.trim().toLocaleLowerCase();

  const visibleUsers = preview?.items.filter((user) => {
    const matchesStatus = filter === "all" || user.status === filter;

    const matchesSearch = (
      `${user.name} ${user.email ?? ""} ${user.id_user}`
    ).toLocaleLowerCase().includes(query);

    return matchesStatus && matchesSearch;
  }) ?? [];

  const suggestedParts = selected?.name.trim().split(/\s+/) ?? [];
  const suggestedName = suggestedParts[0] ?? "";
  const suggestedSurname = suggestedParts.slice(1).join(" ");

  return (
    <section className="aturnos-page">
      <section className="aturnos-panel">
        <h2>Query aTurnos users</h2>

        <p className="aturnos-muted">
          Compare the team with AMH to identify new users and cases
          requiring review.
        </p>

        <form
          className="aturnos-query"
          onSubmit={loadPreview}
          autoComplete="off"
        >
          <fieldset disabled={loading || importing || loadingSaved}>
            <label>
              Team ID
              <input
                name="team_id"
                defaultValue="15945"
                inputMode="numeric"
                pattern="[0-9]+"
                maxLength={64}
                required
              />
            </label>

            <button
              className="users-primary-button"
              type="submit"
            >
              <Search size={16} aria-hidden="true" />
              {loading ? "Querying…" : "Query users"}
            </button>
          </fieldset>
        </form>

        <p className="aturnos-muted">
          AMH uses the configured aTurnos connection.
          Querying does not create users.
        </p>

        {loading && <p role="status">Loading aTurnos users…</p>}

        {error && (
          <p className="aturnos-error" role="alert">{error}</p>
        )}
      </section>
      <section className="aturnos-panel">
        <h2>Last recorded query</h2>

        {loadingSaved && (
          <p role="status">Loading saved comparison…</p>
        )}

        {savedError && (
          <div role="alert">
            <p className="aturnos-error">{savedError}</p>

            <button
              type="button"
              className="users-secondary-button"
              disabled={loadingSaved || loading || importing}
              onClick={() =>
                setSavedRevision((value) => value + 1)
              }
            >
              Retry loading saved result
            </button>
          </div>
        )}

        {savedSync && (
          <>
            {savedSync.latest_run ? (
              <dl className="aturnos-sync-details">
                <div>
                  <dt>Last execution</dt>
                  <dd>
                    {formatSyncDate(
                      savedSync.latest_run.finished_at,
                    )}
                  </dd>
                </div>

                <div>
                  <dt>Result</dt>
                  <dd>
                    {savedSync.latest_run.status === "ok"
                      ? "Successful"
                      : "Failed"}
                  </dd>
                </div>

                <div>
                  <dt>Origin</dt>
                  <dd>
                    {savedSync.latest_run.trigger_kind === "system"
                      ? "System"
                      : "Administrator"}
                  </dd>
                </div>

                <div>
                  <dt>Last successful comparison</dt>
                  <dd>
                    {savedSync.last_success
                      ? formatSyncDate(
                          savedSync.last_success.finished_at,
                        )
                      : "Not available"}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="aturnos-muted">
                No queries have been recorded for this team.
              </p>
            )}

            {savedSync.latest_run?.status === "error" && (
              <p className="aturnos-warning" role="status">
                The latest recorded query failed
                {savedSync.latest_run.error_code
                  ? ` (${savedSync.latest_run.error_code})`
                  : ""}
                .{" "}
                {savedSync.last_success
                  ? "The last successful comparison remains available."
                  : "There is no successful comparison available yet."}
              </p>
            )}

            {savedSync.last_success && (
              <p className="aturnos-muted">
                The table uses a saved comparison. Use Query users
                to obtain current data from aTurnos.
              </p>
            )}
          </>
        )}
      </section>
      {result && (
        <section className="aturnos-panel aturnos-import-success">
          <h2>User created successfully</h2>

          <p>
            {result.name} {result.surname} now has an identity in
            Keycloak and AMH, linked with aTurnos.
          </p>

          <p className="aturnos-muted">
            No application permissions have been assigned.
          </p>

          <div className="aturnos-credentials">
            <label>
              Keycloak username
              <input
                value={result.username}
                readOnly
                autoComplete="off"
              />
            </label>

            <label>
              Temporary password
              <input
                type={showPassword ? "text" : "password"}
                value={result.temporary_password}
                readOnly
                autoComplete="new-password"
              />
            </label>
          </div>

          <p className="aturnos-muted">
            Keep this password in a secure place before clearing it
            or leaving this page. AMH cannot retrieve it later.
          </p>

          <div className="aturnos-actions">
            <button
              type="button"
              className="users-secondary-button"
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? "Hide password" : "Show password"}
            </button>

            <button
              type="button"
              className="users-secondary-button"
              onClick={() => {
                setResult(null);
                setShowPassword(false);
              }}
            >
              Clear credentials
            </button>
          </div>
        </section>
      )}

      {selected && preview && (
        <section className="aturnos-panel">
          <h2>Review and import user</h2>

          <p>
            <strong>aTurnos name:</strong> {selected.name}
          </p>

          <p>
            <strong>Email:</strong> {selected.email}
          </p>

          <p className="aturnos-muted">
            Team {preview.team_id} · User {selected.id_user}
          </p>

          <form
            key={`${preview.team_id}:${selected.id_user}`}
            className="aturnos-import"
            onSubmit={importUser}
            autoComplete="off"
          >
            <fieldset disabled={importing || loadingSaved}>
              <div className="aturnos-name-fields">
                <label>
                  First name
                  <input
                    name="name"
                    defaultValue={suggestedName}
                    maxLength={100}
                    required
                  />
                </label>

                <label>
                  Surname
                  <input
                    name="surname"
                    defaultValue={suggestedSurname}
                    maxLength={150}
                    required
                  />
                </label>
              </div>

              <p className="aturnos-muted">
                The suggested split uses the first word as the first
                name. Correct compound names before importing.
              </p>

              <label className="aturnos-confirm">
                <input type="checkbox" name="reviewed" required />
                <span>
                  I have checked the first name and surname.
                </span>
              </label>

              <div className="aturnos-actions">
                <button
                  type="submit"
                  className="users-primary-button"
                >
                  {importing ? "Creating user…" : "Create user"}
                </button>

                <button
                  type="button"
                  className="users-secondary-button"
                  onClick={() => {
                    setSelected(null);
                    setImportError("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </fieldset>
          </form>

          {importing && (
            <p role="status">
              Verifying aTurnos and creating the identity.
              Please keep this page open.
            </p>
          )}

          {importError && (
            <p className="aturnos-error" role="alert">
              {importError}
            </p>
          )}
        </section>
      )}

      {preview && (
        <section className="aturnos-panel">
          <h2>Team {preview.team_id}</h2>
          <p className="aturnos-muted">
            Returned by aTurnos: <strong>{preview.source_total}</strong>
            {" · "}
            Linked identities not returned:{" "}
            <strong>{preview.missing_total}</strong>
          </p>

          {preview.missing_total > 0 && (
            <p className="aturnos-warning" role="status">
              Some linked users are missing from the current query.
              This does not confirm that they have left the team.
              Check the query scope and dates before changing access.
            </p>
          )}
          <div className="aturnos-summary">
            <div>
              <span>Total</span>
              <strong>{preview.total}</strong>
            </div>

            {(
              ["linked", "new", "inactive", "review"] as const
            ).map((status) => (
              <div key={status}>
                <span>{LABELS[status]}</span>
                <strong>
                  {preview.items.filter(
                    (user) => user.status === status,
                  ).length}
                </strong>
              </div>
            ))}
          </div>

          <div className="aturnos-filters">
            <label>
              Search users
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name, email or ID"
              />
            </label>

            <label>
              Status
              <select
                value={filter}
                onChange={(event) =>
                  setFilter(event.target.value as Filter)
                }
              >
                <option value="all">All</option>
                <option value="linked">Linked</option>
                <option value="new">New</option>
                <option value="inactive">Inactive</option>
                <option value="review">Review</option>
              </select>
            </label>
          </div>

          <p className="aturnos-muted">
            Showing {visibleUsers.length} of {preview.total} users.
            Linked indicates a stored identity match in AMH.
          </p>

          {result && (
            <p className="aturnos-muted">
              Save and clear the credentials above before importing
              another user.
            </p>
          )}

          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>aTurnos email</th>
                  <th>AMH email</th>
                  <th>aTurnos ID</th>
                  <th>Status</th>
                  <th>Details</th>
                  <th>Action</th>
                </tr>
              </thead>

              <tbody>
                {visibleUsers.map((user, index) => (
                  <tr key={`${user.id_user}:${index}`}>
                    <td>{user.name || "—"}</td>

                    <td>
                      {user.source_present
                        ? user.email ?? "—"
                        : "Not returned"}
                    </td>

                    <td
                      className={
                        user.amh_user_id &&
                        user.source_present &&
                        (user.email ?? "").trim().toLowerCase() !==
                          (user.amh_primary_email ?? "")
                            .trim()
                            .toLowerCase()
                          ? "aturnos-email-difference"
                          : undefined
                      }
                    >
                      {user.amh_primary_email ?? "—"}
                    </td>

                    <td>{user.id_user}</td>

                    <td>
                      <span
                        className={`aturnos-badge ${user.status}`}
                      >
                        {LABELS[user.status]}
                      </span>
                    </td>

                    <td>{user.reason}</td>

                    <td>
                      {user.amh_user_id ? (
                        <button
                          type="button"
                          className="users-secondary-button"
                          disabled={importing}
                          onClick={() => {
                            if (user.amh_user_id) {
                              onManageUser(user.amh_user_id);
                            }
                          }}
                        >
                          Open user
                        </button>
                      ) : user.status === "new" ? (
                        <button
                          type="button"
                          className="users-primary-button"
                          disabled={
                            importing ||
                            loading ||
                            loadingSaved ||
                            result !== null
                          }
                          onClick={() => selectUser(user)}
                        >
                          Review and import
                        </button>
                      ) : "—"}
                    </td>
                  </tr>
                ))}

                {visibleUsers.length === 0 && (
                  <tr>
                    <td colSpan={7}>No matching users.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
            <ATurnosHistory
        onSessionExpired={onSessionExpired}
        onManageUser={onManageUser}
        refreshKey={result?.user_id ?? ""}
      />
    </section>
  );
}