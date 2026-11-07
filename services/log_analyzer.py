import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone

LEVELS = ("CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG")
TIME_RE = re.compile(r"\d{4}-\d\d-\d\d[T ][0-9:.+-]+Z?")
LEVEL_RE = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG)\b", re.I)
SERVICE_RE = re.compile(r"(?:service|component|logger)[=: ]+([\w.-]+)", re.I)


def _timestamp(value):
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_events(text):
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return None
    rows = parsed if isinstance(parsed, list) else parsed.get("events", [parsed]) if isinstance(parsed, dict) else []
    if not isinstance(rows, list):
        return None
    result = []
    for row in rows[:5000]:
        if isinstance(row, str):
            row = {"message": row}
        if not isinstance(row, dict):
            continue
        message = str(row.get("message", row.get("msg", row.get("body", ""))))[:1500]
        if not message:
            continue
        level = str(row.get("level", row.get("severity", "INFO"))).upper()
        if level == "WARNING":
            level = "WARN"
        result.append({"timestamp": _timestamp(row.get("timestamp", row.get("time"))), "level": level if level in LEVELS else "INFO", "service": str(row.get("service", row.get("component", "unknown")))[:100], "message": message})
    return result


def parse_logs(raw, max_chars=16000):
    raw = str(raw or "")[:max_chars]
    events = _json_events(raw)
    if events is None:
        events = []
        for line in raw.splitlines()[:5000]:
            line = line.strip()
            if not line:
                continue
            stamp = TIME_RE.search(line)
            lev = LEVEL_RE.search(line)
            svc = SERVICE_RE.search(line)
            events.append({"timestamp": _timestamp(stamp.group(0) if stamp else None), "level": lev.group(1).upper().replace("WARNING", "WARN") if lev else "INFO", "service": svc.group(1) if svc else "unknown", "message": line[:1500]})
    events.sort(key=lambda e: e["timestamp"])
    counts = Counter(e["level"] for e in events)
    normalized = "\n".join(f"{e['level']} {e['service']} {e['message']}" for e in events)
    fingerprint = hashlib.sha256(re.sub(r"\d+", "#", normalized.lower()).encode()).hexdigest()
    important = [e for e in events if e["level"] in ("CRITICAL", "FATAL", "ERROR", "WARN")]
    freq = Counter(e["message"] for e in important)
    repeated = [{"message": msg, "count": count} for msg, count in freq.most_common(8) if count > 1]
    services = sorted({e["service"] for e in events if e["service"] != "unknown"})
    summary = f"{len(events)} events; {counts['ERROR'] + counts['CRITICAL'] + counts['FATAL']} errors and {counts['WARN']} warnings across {', '.join(services[:4]) or 'unidentified services'}."
    evidence = "\n".join(f"{e['timestamp'].isoformat(timespec='seconds')} [{e['level']}] {e['service']}: {e['message']}" for e in (important[-30:] or events[-15:]))
    return {"events": events, "summary": summary, "counts": dict(counts), "services": services, "repeated": repeated, "fingerprint": fingerprint, "evidence": evidence[:6000], "first_seen": events[0]["timestamp"] if events else datetime.now(timezone.utc).replace(tzinfo=None), "last_seen": events[-1]["timestamp"] if events else datetime.now(timezone.utc).replace(tzinfo=None)}


def otel_event_adapter(record):
    """Map a normalized OpenTelemetry LogRecord-like mapping to Chronoops event input."""
    attrs = record.get("attributes") or {}
    return {"timestamp": record.get("time_unix_nano") or record.get("timestamp"), "severity": record.get("severity_text", "INFO"), "body": record.get("body", ""), "service": attrs.get("service.name", record.get("service_name", "unknown"))}
