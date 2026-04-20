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
from typing import Optional

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


def _update_sync_status(log_id: int, synced: bool, error: str = ''):
    """
    Safely updates the frappe_synced / frappe_error fields on an
    AttendanceLog record.  Does nothing if log_id is None or the
    record doesn't exist.
    """
    if log_id is None:
        return
    try:
        from .models import AttendanceLog
        AttendanceLog.objects.filter(pk=log_id).update(
            frappe_synced=synced,
            frappe_error=error,
        )
    except Exception as exc:
        logger.warning("[FRAPPE HRMS] Could not update sync status for log %s: %s", log_id, exc)


def submit_log_to_frappe(log):
    """
    Re-submits a single AttendanceLog instance to Frappe HRMS.
    Designed to be called from the Django admin action.

    Args:
        log: An AttendanceLog model instance.

    Returns:
        (bool, str): Tuple of (success, message).
    """
    from .models import AttendanceLog
    from .utils import MANILA_TZ

    # Determine the Frappe log_type (IN/OUT) from the local log_type code
    log_type_to_action = {'MI': 'IN', 'MO': 'OUT', 'AI': 'IN', 'AO': 'OUT'}
    frappe_action = log_type_to_action.get(log.log_type, log.action)

    log_display = log.get_log_type_display() or log.action

    payload = {
        'username':         log.username,
        'log_type':         log.log_type or '',
        'log_type_display': log_display,
        'action':           frappe_action,
        'timestamp':        log.timestamp.astimezone(MANILA_TZ).isoformat(),
    }

    try:
        _push_checkin_to_frappe(payload, log_type=frappe_action, log_id=log.pk)
        return True, f"✓ Synced {log.username} ({log_display})"
    except Exception as exc:
        error_msg = str(exc)
        _update_sync_status(log.pk, synced=False, error=error_msg)
        return False, f"✗ Failed {log.username} ({log_display}): {error_msg}"


# ---------------------------------------------------------------------------
# Employee info lookup (safe — never raises)
# ---------------------------------------------------------------------------

def fetch_employee_info(username: str) -> Optional[dict]:
    """
    Fetches employee details (full name, department, designation) from
    Frappe HRMS via the REST resource API.

    This is designed to be **safe for synchronous use** in the login flow:
      - Returns a dict on success:
            {"employee_name": "...", "department": "...", "designation": "..."}
      - Returns None on ANY failure (missing config, network error,
        employee not found, unexpected response shape).
      - Never raises — all exceptions are caught and logged.

    Usage in views.py:
        info = handlers.fetch_employee_info(matched_face.username)
        # info is None  → just use username as before
        # info is a dict → enrich the response
    """
    try:
        config = _get_frappe_config()
    except RuntimeError:
        # Frappe not configured — silently return None
        return None

    base_url   = config["BASE_URL"].rstrip("/")
    api_key    = config["API_KEY"]
    api_secret = config["API_SECRET"]
    timeout    = config.get("TIMEOUT", 10)
    employee_field = config.get("EMPLOYEE_FIELDNAME", "attendance_device_id")

    headers = {
        "Host": base_url,
        "Authorization": f"token {api_key}:{api_secret}",
        "Accept":        "application/json",
    }

    fields = '["employee_name","department","designation","company"]'

    # If EMPLOYEE_FIELDNAME is "name", we can hit the resource directly.
    # Otherwise we need to filter by the custom field.
    if employee_field == "name":
        url = f"{base_url}/api/resource/Employee/{username}?fields={fields}"
    else:
        import json as _json
        filters = _json.dumps([["Employee", employee_field, "=", username]])
        url = (
            f"{base_url}/api/resource/Employee"
            f"?filters={filters}&fields={fields}&limit_page_length=1"
        )

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(
            "[FRAPPE HRMS] Could not fetch employee info for '%s': %s",
            username, exc,
        )
        return None

    # Direct resource lookup returns {"data": {…}}
    # List lookup returns            {"data": [{…}, …]}
    try:
        payload_data = data.get("data")
        if isinstance(payload_data, dict):
            employee = payload_data
        elif isinstance(payload_data, list) and payload_data:
            employee = payload_data[0]
        else:
            logger.info(
                "[FRAPPE HRMS] Employee '%s' not found in Frappe.", username
            )
            return None

        return {
            "employee_name": employee.get("employee_name", ""),
            "department":    employee.get("department", ""),
            "designation":   employee.get("designation", ""),
            "office":        employee.get("company", ""),
        }
    except Exception as exc:
        logger.warning(
            "[FRAPPE HRMS] Unexpected response shape for '%s': %s",
            username, exc,
        )
        return None


def _push_checkin_to_frappe(payload: dict, log_type: str, log_id: int = None):
    """
    Core integration function.  Sends a single Employee Check-in record
    to Frappe HRMS using the recommended server-side method endpoint.

    Args:
        payload:  The event payload dict passed by views.py.
        log_type: "IN" or "OUT" — the Frappe log_type value.
        log_id:   Optional AttendanceLog PK — used to update sync status.

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
        "Host": "ims.penroaklan.com.ph",
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

    # Mark as synced in the database
    _update_sync_status(log_id, synced=True, error='')

    return result


# ---------------------------------------------------------------------------
# Morning In  (MI)
# ---------------------------------------------------------------------------
def on_morning_in(payload: dict, log_id: int = None):
    """
    Called when an employee successfully logs Morning In.
    Pushes an Employee Check-in record (log_type='IN') to Frappe HRMS.

    Frappe will pick this up for auto-attendance calculation based on
    the matching employee's Shift Type / Shift Assignment.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="IN", log_id=log_id)
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_morning_in: %s", exc)
        _update_sync_status(log_id, synced=False, error=str(exc))
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Morning In for '%s'. "
            "The record was saved locally; Frappe will not have it.",
            payload["username"],
        )
        _update_sync_status(log_id, synced=False, error='Timeout')
    except requests.exceptions.HTTPError as exc:
        error_detail = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        logger.error(
            "[FRAPPE HRMS] HTTP error on Morning In for '%s': %s",
            payload["username"], error_detail,
        )
        _update_sync_status(log_id, synced=False, error=error_detail)
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_morning_in for '%s': %s",
            payload["username"], exc,
        )
        _update_sync_status(log_id, synced=False, error=str(exc))


# ---------------------------------------------------------------------------
# Morning Out  (MO)
# ---------------------------------------------------------------------------
def on_morning_out(payload: dict, log_id: int = None):
    """
    Called when an employee successfully logs Morning Out.
    Pushes an Employee Check-in record (log_type='OUT') to Frappe HRMS.

    Note: In many Frappe HRMS setups the morning break-out is recorded
    so the system can compute actual working hours accurately.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="OUT", log_id=log_id)
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_morning_out: %s", exc)
        _update_sync_status(log_id, synced=False, error=str(exc))
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Morning Out for '%s'.", payload["username"]
        )
        _update_sync_status(log_id, synced=False, error='Timeout')
    except requests.exceptions.HTTPError as exc:
        error_detail = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        logger.error(
            "[FRAPPE HRMS] HTTP error on Morning Out for '%s': %s",
            payload["username"], error_detail,
        )
        _update_sync_status(log_id, synced=False, error=error_detail)
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_morning_out for '%s': %s",
            payload["username"], exc,
        )
        _update_sync_status(log_id, synced=False, error=str(exc))


# ---------------------------------------------------------------------------
# Afternoon In  (AI)
# ---------------------------------------------------------------------------
def on_afternoon_in(payload: dict, log_id: int = None):
    """
    Called when an employee successfully logs Afternoon In.
    Pushes an Employee Check-in record (log_type='IN') to Frappe HRMS.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="IN", log_id=log_id)
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_afternoon_in: %s", exc)
        _update_sync_status(log_id, synced=False, error=str(exc))
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Afternoon In for '%s'.", payload["username"]
        )
        _update_sync_status(log_id, synced=False, error='Timeout')
    except requests.exceptions.HTTPError as exc:
        error_detail = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        logger.error(
            "[FRAPPE HRMS] HTTP error on Afternoon In for '%s': %s",
            payload["username"], error_detail,
        )
        _update_sync_status(log_id, synced=False, error=error_detail)
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_afternoon_in for '%s': %s",
            payload["username"], exc,
        )
        _update_sync_status(log_id, synced=False, error=str(exc))


# ---------------------------------------------------------------------------
# Afternoon Out  (AO)
# ---------------------------------------------------------------------------
def on_afternoon_out(payload: dict, log_id: int = None):
    """
    Called when an employee successfully logs Afternoon Out.
    Pushes an Employee Check-in record (log_type='OUT') to Frappe HRMS.

    This is typically the final event that allows Frappe's auto-attendance
    to mark the employee as 'Present' for the day.
    """
    try:
        _push_checkin_to_frappe(payload, log_type="OUT", log_id=log_id)
    except RuntimeError as exc:
        logger.error("[FRAPPE HRMS] Configuration error in on_afternoon_out: %s", exc)
        _update_sync_status(log_id, synced=False, error=str(exc))
    except requests.exceptions.Timeout:
        logger.warning(
            "[FRAPPE HRMS] Timeout on Afternoon Out for '%s'.", payload["username"]
        )
        _update_sync_status(log_id, synced=False, error='Timeout')
    except requests.exceptions.HTTPError as exc:
        error_detail = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        logger.error(
            "[FRAPPE HRMS] HTTP error on Afternoon Out for '%s': %s",
            payload["username"], error_detail,
        )
        _update_sync_status(log_id, synced=False, error=error_detail)
    except Exception as exc:
        logger.exception(
            "[FRAPPE HRMS] Unexpected error in on_afternoon_out for '%s': %s",
            payload["username"], exc,
        )
        _update_sync_status(log_id, synced=False, error=str(exc))


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
    manual_date = "2026-04-16"
    test_sequence = [
        ("MI", "Morning In",    "IN",  f"{manual_date}T08:00:07+33:00", on_morning_in),
        ("MO", "Morning Out",   "OUT", f"{manual_date}T12:00:05+08:00", on_morning_out),
        ("AI", "Afternoon In",  "IN",  f"{manual_date}T13:00:10+08:00", on_afternoon_in),
        ("AO", "Afternoon Out", "OUT", f"{manual_date}T17:00:18+08:00", on_afternoon_out),
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
