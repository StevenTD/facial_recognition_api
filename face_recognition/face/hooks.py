import json
import logging
import threading
import requests
from .models import WebhookConfig

logger = logging.getLogger(__name__)



def _send_webhook(config, payload):
    """Internal function executed in a background thread for each webhook call."""
    try:
        headers = {'Content-Type': 'application/json'}
        headers.update(config.custom_headers or {})

        if config.method == 'POST':
            response = requests.post(
                config.url,
                data=json.dumps(payload),
                headers=headers,
                timeout=config.timeout
            )
        else:  # GET
            response = requests.get(
                config.url,
                params=payload,
                headers=headers,
                timeout=config.timeout
            )

        logger.info(
            f"[Webhook] '{config.name}' fired for {payload.get('log_type')} "
            f"→ {config.url} — HTTP {response.status_code}"
        )
    except requests.exceptions.Timeout:
        logger.warning(f"[Webhook] '{config.name}' timed out after {config.timeout}s → {config.url}")
    except requests.exceptions.ConnectionError:
        logger.warning(f"[Webhook] '{config.name}' connection error → {config.url}")
    except Exception as e:
        logger.error(f"[Webhook] '{config.name}' unexpected error: {e}")


def _safe_call(handler_fn, payload):
    """Internal wrapper that runs a code-level handler and catches any exception."""
    try:
        handler_fn(payload)
    except Exception as e:
        logger.error(f"[Handler] {handler_fn.__name__} raised an error: {e}")


def fire_webhooks(log_type, payload):
    """
    Dispatch all enabled WebhookConfigs that match the given log_type.
    Each request fires in a background daemon thread (non-blocking).

    Code-level handlers (handlers.py) are called directly in views.py,
    so this function only handles admin-configured webhook URLs.

    Args:
        log_type (str): One of 'MI', 'MO', 'AI', 'AO'
        payload (dict): Data to send. Keys:
                        username, log_type, log_type_display, action, timestamp
    """
    try:
        configs = WebhookConfig.objects.filter(is_enabled=True)
    except Exception as e:
        logger.error(f"[Webhook] Failed to query WebhookConfig: {e}")
        return

    triggered = 0
    for config in configs:
        active_types = [t.strip() for t in config.log_types.split(',') if t.strip()]
        if log_type in active_types:
            t = threading.Thread(target=_send_webhook, args=(config, payload), daemon=True)
            t.start()
            triggered += 1

    if triggered:
        logger.info(f"[Webhook] {triggered} config hook(s) triggered for log_type='{log_type}'")

