"""
Attendance Event Handlers  —  Frappe HRMS Integration
======================================================
Each function is called from a background thread immediately after a
successful attendance log is saved in the local database.

The login response is NEVER delayed — these handlers run asynchronously.

──────────────────────────────────────────────────────────────────────────
Payload received by every handler:
    {
        "username":         str  — employee ID / username (used to look up
                                   the employee in Frappe HRMS)
        "log_type":         str  — "MI" | "MO" | "AI" | "AO"
        "log_type_display": str  — "Morning In" | "Morning Out" | ...
        "action":           str  — "IN" | "OUT"
        "timestamp":        str  — ISO-8601 string in Asia/Manila timezone
                                   (same value as the DB record)
    }
──────────────────────────────────────────────────────────────────────────
Frappe HRMS endpoint used:
    POST /api/method/hrms.hr.doctype.employee_checkin.employee_checkin.add_log_based_on_employee_field

    Required params:
        employee_field_value  — the employee's identifier (e.g. attendance_device_id or name)
        timestamp             — "YYYY-MM-DD HH:MM:SS" format
        log_type              — "IN" or "OUT"
        employee_fieldname    — the Frappe Employee field to match against
                                (default: "attendance_device_id")
        device_id             — optional label for this kiosk/location

──────────────────────────────────────────────────────────────────────────
Configuration (add to Django settings.py):

    FRAPPE_HRMS = {
        # Base URL of your Frappe / ERPNext site (no trailing slash)
        "BASE_URL": "https://your-erp.example.com",

        # API credentials — generate via ERPNext > User > API Access
        # NEVER commit real secrets; use environment variables in production.
        "API_KEY":    "your_api_key_here",
        "API_SECRET": "your_api_secret_here",

        # The Employee docfield whose value matches payload["username"].
        # Common choices: "attendance_device_id", "name", "employee_number"
        "EMPLOYEE_FIELDNAME": "attendance_device_id",

        # Optional: label sent to Frappe to identify this kiosk / installation
        "DEVICE_ID": "FACIAL_RECOGNITION_KIOSK_01",

        # Request timeout in seconds
        "TIMEOUT": 10,
    }
──────────────────────────────────────────────────────────────────────────
"""

import logging
from datetime import datetime

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_frappe_config():
    """
    Returns the FRAPPE_HRMS settings dict.
    Raises a clear RuntimeError if the block is missing so developers
    know exactly what to configure.
    """
    config = getattr(settings, "FRAPPE_HRMS", None)
    if not config:
        raise RuntimeError(
            "FRAPPE_HRMS is not configured in settings.py. "
            "Please add the FRAPPE_HRMS dict (see handlers.py docstring)."
        )
    required = ("BASE_URL", "API_KEY", "API_SECRET")
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise RuntimeError(
            f"FRAPPE_HRMS settings are incomplete. Missing: {missing}"
        )
    return config


def _parse_timestamp(iso_timestamp: str) -> str:
    """
    Converts an ISO-8601 string (e.g. '2026-04-17T08:00:00+08:00')
    to the Frappe-expected format: 'YYYY-MM-DD HH:MM:SS'.
    """
    # fromisoformat handles offset-aware strings in Python 3.7+
    dt = datetime.fromisoformat(iso_timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _push_checkin_to_frappe(payload: dict, log_type: str):
    """
    Core integration function.  Sends a single Employee Check-in record
    to Frappe HRMS using the recommended server-side method endpoint.

    Args:
        payload:  The event payload dict passed by views.py.
        log_type: "IN" or "OUT" — the Frappe log_type value.

    Returns:
        dict: Parsed JSON response from Frappe on success.

    Raises:
        requests.HTTPError: If Frappe returns a non-2xx status.
        RuntimeError: If FRAPPE_HRMS settings are missing.
    """
    config = _get_frappe_config()

    base_url        = config["BASE_URL"].rstrip("/")
    api_key         = config["API_KEY"]
    api_secret      = config["API_SECRET"]
    employee_field  = config.get("EMPLOYEE_FIELDNAME", "attendance_device_id")
    device_id       = config.get("DEVICE_ID", "FACIAL_RECOGNITION_KIOSK")
    timeout         = config.get("TIMEOUT", 10)

    endpoint = (
        f"{base_url}/api/method/"
        "hrms.hr.doctype.employee_checkin.employee_checkin"
        ".add_log_based_on_employee_field"
    )

    headers = {
        "Host": "development.localhost",
        "Authorization": f"token {api_key}:{api_secret}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }

    frappe_timestamp = _parse_timestamp(payload["timestamp"])

    body = {
        "employee_field_value": payload["username"],
        "timestamp":            frappe_timestamp,
        "log_type":             log_type,            # "IN" or "OUT"
        "employee_fieldname":   employee_field,
        "device_id":            device_id,
    }

    logger.info(
        "[FRAPPE HRMS] Sending %s check-in for employee '%s' at %s",
        log_type, payload["username"], frappe_timestamp,
    )

    response = requests.post(endpoint, json=body, headers=headers, timeout=timeout)

    # Log full response for debugging; raise on error
    logger.debug("[FRAPPE HRMS] Response %s: %s", response.status_code, response.text[:500])
    response.raise_for_status()

    result = response.json()
    logger.info(
        "[FRAPPE HRMS] ✓ Check-in created for '%s' | log_type=%s | frappe_response=%s",
        payload["username"], log_type, result.get("message", result),
    )
    return result


# ---------------------------------------------------------------------------
# Morning In  (MI)
# ---------------------------------------------------------------------------
def on_morning_in(payload: dict):
    """
    Called when an employee successfully logs Morning In.
    Pushes an Employee Check-in record (log_type='IN') to Frappe HRMS.

    Frappe will pick this up for auto-attendance calculation based on
    the matching employee's Shift Type / Shift Assignment.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="IN")
    except RuntimeError as exc:
        # Configuration error — log prominently so the admin notices
        logger.error("[FRAPPE HRMS] Configuration error in on_morning_in: %s", exc)
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Morning In for '%s'. "
            "The record was saved locally; Frappe will not have it.",
            payload["username"],
        )
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "[FRAPPE HRMS] HTTP error on Morning In for '%s': %s — %s",
            payload["username"], exc.response.status_code, exc.response.text[:300],
        )
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_morning_in for '%s': %s",
            payload["username"], exc,
        )


# ---------------------------------------------------------------------------
# Morning Out  (MO)
# ---------------------------------------------------------------------------
def on_morning_out(payload: dict):
    """
    Called when an employee successfully logs Morning Out.
    Pushes an Employee Check-in record (log_type='OUT') to Frappe HRMS.

    Note: In many Frappe HRMS setups the morning break-out is recorded
    so the system can compute actual working hours accurately.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="OUT")
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_morning_out: %s", exc)
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Morning Out for '%s'.", payload["username"]
        )
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "[FRAPPE HRMS] HTTP error on Morning Out for '%s': %s — %s",
            payload["username"], exc.response.status_code, exc.response.text[:300],
        )
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_morning_out for '%s': %s",
            payload["username"], exc,
        )


# ---------------------------------------------------------------------------
# Afternoon In  (AI)
# ---------------------------------------------------------------------------
def on_afternoon_in(payload: dict):
    """
    Called when an employee successfully logs Afternoon In.
    Pushes an Employee Check-in record (log_type='IN') to Frappe HRMS.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="IN")
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_afternoon_in: %s", exc)
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Afternoon In for '%s'.", payload["username"]
        )
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "[FRAPPE HRMS] HTTP error on Afternoon In for '%s': %s — %s",
            payload["username"], exc.response.status_code, exc.response.text[:300],
        )
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_afternoon_in for '%s': %s",
            payload["username"], exc,
        )


# ---------------------------------------------------------------------------
# Afternoon Out  (AO)
# ---------------------------------------------------------------------------
def on_afternoon_out(payload: dict):
    """
    Called when an employee successfully logs Afternoon Out.
    Pushes an Employee Check-in record (log_type='OUT') to Frappe HRMS.

    This is typically the final event that allows Frappe's auto-attendance
    to mark the employee as 'Present' for the day.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="OUT")
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_afternoon_out: %s", exc)
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Afternoon Out for '%s'.", payload["username"]
        )
    except requests.exceptions.HTTPError as exc:
        logger.error(
            "[FRAPPE HRMS] HTTP error on Afternoon Out for '%s': %s — %s",
            payload["username"], exc.response.status_code, exc.response.text[:300],
        )
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_afternoon_out for '%s': %s",
            payload["username"], exc,
        )


# ---------------------------------------------------------------------------
# Debug & Manual Testing
# ---------------------------------------------------------------------------

def debug_test_frappe_integration(username: str):
    """
    Manual test utility to verify Frappe HRMS connectivity without the frontend.
    Run this from the terminal:
        python manage.py shell
        >>> from face.handlers import debug_test_frappe_integration
        >>> debug_test_frappe_integration("EMP-12345")
    """
    from django.utils import timezone

    # Use today's date with realistic sample timestamps
    today_str = timezone.localtime().strftime("%Y-%m-%d")

    test_sequence = [
        ("MI", "Morning In",    "IN",  f"{today_str}T08:00:00+08:00", on_morning_in),
        ("MO", "Morning Out",   "OUT", f"{today_str}T12:00:05+08:00", on_morning_out),
        ("AI", "Afternoon In",  "IN",  f"{today_str}T13:00:10+08:00", on_afternoon_in),
        ("AO", "Afternoon Out", "OUT", f"{today_str}T17:00:15+08:00", on_afternoon_out),
    ]

    print(f"\n🚀 Starting Frappe Integration Test for: {username}")
    print("-" * 50)

    for code, display, action, ts, handler in test_sequence:
        payload = {
            "username": username,
            "log_type": code,
            "log_type_display": display,
            "action": action,
            "timestamp": ts,
        }
        print(f"🔹 Simulating {display} ({code})...")
        handler(payload)

    print("-" * 50)
    print("✅ Test sequence complete. Check your server logs or Frappe dashboard.\n")
