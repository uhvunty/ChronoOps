import argparse

from services.hindsight_service import (
    initialize_hindsight,
    retain_incident,
    recall_incidents
)

def main():
    parser = argparse.ArgumentParser(description="Opt-in live Hindsight integration smoke test.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="allow this script to initialize the configured bank and retain TEST-001",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("this script makes live Hindsight calls; pass --live only when intended")

    print("\n1. Initializing Hindsight...")

    success, message = initialize_hindsight()
    print(success, message)

    if not success:
        raise SystemExit("Hindsight initialization failed.")

    print("\n2. Retaining a test incident...")

    result = retain_incident(
        incident_id="TEST-001",
        title="Database connection pool exhausted",
        service="Authentication API",
        severity="Critical",
        root_cause="Database connections were not released.",
        resolution="Released stale connections and corrected cleanup.",
        lessons="Monitor connection pool utilization.",
        impact="Authentication requests failed."
    )

    print(result)

    print("\n3. Recalling the test incident...")

    result = recall_incidents(
        "Authentication API database connection pool exhaustion"
    )

    print(result)


if __name__ == "__main__":
    main()
