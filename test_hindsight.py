from services.hindsight_service import (
    initialize_hindsight,
    retain_incident,
    recall_incidents
)

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
