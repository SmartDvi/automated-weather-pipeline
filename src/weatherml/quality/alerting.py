import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertEvent:
    check_name: str
    location_key: str | None
    severity: str
    details: dict


def notify(event: AlertEvent) -> None:
    """Alert hook stub: logs at WARNING/CRITICAL. This is the integration
    point for a real paging/notification channel (Slack, PagerDuty, email) —
    deliberately not wired further; see docs/next_steps.md. Every alerting
    call site already funnels through here, so wiring a real channel later
    is a one-function change, not a search-and-replace across the codebase.
    """
    log_level = logging.CRITICAL if event.severity == "critical" else logging.WARNING
    logger.log(
        log_level,
        "data_quality_alert",
        extra={
            "check_name": event.check_name,
            "location_key": event.location_key,
            "severity": event.severity,
            "details": event.details,
        },
    )
