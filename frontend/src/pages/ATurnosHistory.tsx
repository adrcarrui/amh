import { useEffect, useState } from "react";

type HistoryEvent = {
  id: string;
  user_id: string;
  user_name: string;
  actor_user_id: string;
  actor_name: string;
  id_aturno: string;
  id_user: string;
  occurred_at: string;
};

type HistoryResponse = {
  total: number;
  limit: number;
  offset: number;
  items: HistoryEvent[];
};

type Props = {
  onSessionExpired: () => void;
  onManageUser: (userId: string) => void;
  refreshKey: string;
};

const PAGE_SIZE = 25;

function isHistoryEvent(value: unknown): value is HistoryEvent {
  if (typeof value !== "object" || value === null) return false;

  const item = value as Record<string, unknown>;

  return [
    "id",
    "user_id",
    "user_name",
    "actor_user_id",
    "actor_name",
    "id_aturno",
    "id_user",
    "occurred_at",
  ].every((key) => typeof item[key] === "string");
}

function isHistoryResponse(value: unknown): value is HistoryResponse {
  if (typeof value !== "object" || value === null) return false;

  const data = value as Record<string, unknown>;

  return (
    typeof data.total === "number" &&
    Number.isInteger(data.total) &&
    data.total >= 0 &&
    typeof data.limit === "number" &&
    data.limit === PAGE_SIZE &&
    typeof data.offset === "number" &&
    Number.isInteger(data.offset) &&
    data.offset >= 0 &&
    Array.isArray(data.items) &&
    data.items.every(isHistoryEvent) &&
    data.items.length <= PAGE_SIZE
  );
}

function formatDate(value: string): string {
  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString();
}

export function ATurnosHistory({
  onSessionExpired,
  onManageUser,
  refreshKey,
}: Props) {
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;

    const timeout = window.setTimeout(
      () => controller.abort(),
      10000,
    );

    async function loadHistory() {
      setLoading(true);
      setError("");
      setHistory(null);

      try {
        const params = new URLSearchParams({
          limit: String(PAGE_SIZE),
          offset: String(offset),
        });

        const response = await fetch(
          `/api/v1/admin/aturnos/history?${params}`,
          {
            credentials: "include",
            cache: "no-store",
            signal: controller.signal,
          },
        );

        if (disposed) return;

        if (response.status === 401) {
          onSessionExpired();
          return;
        }

        const data: unknown = await response.json().catch(() => null);

        if (!response.ok) {
          const message =
            typeof data === "object" &&
            data !== null &&
            "detail" in data &&
            typeof data.detail === "string"
              ? data.detail
              : "Unable to load import history.";

          throw new Error(message);
        }

        if (!isHistoryResponse(data) || data.offset !== offset) {
          throw new Error("Invalid import history response.");
        }

        if (!disposed) {
          setHistory(data);
        }
      } catch (cause) {
        if (!disposed) {
          setError(
            controller.signal.aborted
              ? "The history request took too long."
              : cause instanceof Error
                ? cause.message
                : "Unable to load import history.",
          );
        }
      } finally {
        window.clearTimeout(timeout);

        if (!disposed) {
          setLoading(false);
        }
      }
    }

    void loadHistory();

    return () => {
      disposed = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [offset, revision, refreshKey, onSessionExpired]);

  return (
    <section className="aturnos-panel">
      <div className="aturnos-history-heading">
        <div>
          <h2>Import history</h2>
          <p className="aturnos-muted">
            Successful imports recorded since auditing was enabled.
          </p>
        </div>

        <button
          type="button"
          className="users-secondary-button"
          disabled={loading}
          onClick={() => {
            setOffset(0);
            setRevision((value) => value + 1);
          }}
        >
          Refresh history
        </button>
      </div>

      {loading && <p role="status">Loading import history…</p>}

      {error && (
        <p className="aturnos-error" role="alert">{error}</p>
      )}

      {!loading && history && (
        <>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Imported user</th>
                  <th>Administrator</th>
                  <th>Team ID</th>
                  <th>aTurnos ID</th>
                  <th>Action</th>
                </tr>
              </thead>

              <tbody>
                {history.items.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <time dateTime={event.occurred_at}>
                        {formatDate(event.occurred_at)}
                      </time>
                    </td>

                    <td>{event.user_name}</td>
                    <td>{event.actor_name}</td>
                    <td>{event.id_aturno}</td>
                    <td>{event.id_user}</td>

                    <td>
                      <button
                        type="button"
                        className="users-secondary-button"
                        onClick={() => onManageUser(event.user_id)}
                      >
                        Open user
                      </button>
                    </td>
                  </tr>
                ))}

                {history.items.length === 0 && (
                  <tr>
                    <td colSpan={6}>
                      No imports recorded yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="aturnos-history-pagination">
            <span className="aturnos-muted">
              {history.items.length > 0
                ? `${offset + 1}–${offset + history.items.length}`
                : "0"}{" "}
              of {history.total} imports
            </span>

            <div className="aturnos-actions">
              <button
                type="button"
                className="users-secondary-button"
                disabled={offset === 0}
                onClick={() =>
                  setOffset((value) => Math.max(0, value - PAGE_SIZE))
                }
              >
                Previous
              </button>

              <button
                type="button"
                className="users-secondary-button"
                disabled={
                  offset + history.items.length >= history.total ||
                  history.items.length === 0
                }
                onClick={() =>
                  setOffset((value) => value + PAGE_SIZE)
                }
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}