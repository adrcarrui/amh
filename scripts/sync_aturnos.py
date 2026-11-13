from collections import Counter

from app.aturnos_sync_service import (
    ATurnosSyncError,
    run_aturnos_sync,
)


def main():
    result = run_aturnos_sync(trigger_kind="system")
    counts = Counter(item["status"] for item in result["items"])

    print(f"Ejecucion: {result['run_id']}")
    print(f"Equipo: {result['team_id']}")
    print(f"Finalizada: {result['finished_at']}")
    print(f"Usuarios devueltos: {result['source_total']}")
    print(f"Enlaces ausentes: {result['missing_total']}")

    for status in ("linked", "new", "inactive", "review"):
        print(f"{status}: {counts[status]}")

    print("\nConsulta registrada.")
    print("No se han creado usuarios ni modificado accesos.")


if __name__ == "__main__":
    try:
        main()
    except ATurnosSyncError as exc:
        print(f"ERROR [{exc.code}]: {exc}")
        raise SystemExit(1)