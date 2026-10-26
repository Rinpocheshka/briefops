"""Shared server-side definitions for queues, counters and response deadlines."""
REVIEW_STATUSES = {"queued", "processing", "ready", "needs_info", "retry", "failed"}


def bucket(lead):
    if lead["status"] == "duplicate":
        return "duplicate"
    if (lead.get("email_delivery") or {}).get("status") == "sent":
        return "sent"
    return "approved" if lead["status"] == "approved" else "review"


def overdue(lead, workspace, now):
    closed = bucket(lead) in ({"sent", "duplicate"} if workspace else {"approved", "sent", "duplicate"})
    return not closed and lead["sla_at"] <= now


def summarize(leads, workspace, now):
    counts = {name: sum(bucket(lead) == name for lead in leads) for name in ("review", "approved", "sent", "duplicate")}
    counts.update(total=len(leads), duplicates=counts.pop("duplicate"), pending=counts["review"] + counts["approved"],
                  sla=sum(overdue(lead, workspace, now) for lead in leads),
                  errors=sum(lead["status"] == "failed" or (lead.get("email_delivery") or {}).get("status") in {"failed", "uncertain"} for lead in leads),
                  notification_errors=sum((lead.get("email_notification") or {}).get("status") in {"failed", "uncertain"} for lead in leads))
    return counts
