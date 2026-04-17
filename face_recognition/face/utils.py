import datetime
import pytz
from django.utils import timezone
from .models import AttendanceLog

# Manila Timezone
MANILA_TZ = pytz.timezone('Asia/Manila')

# Configurable Time Windows
# Format: (log_type, action, start_time, end_time)
ATTENDANCE_WINDOWS = [
    ('MI', 'IN', datetime.time(0, 0), datetime.time(12, 0)),
    ('MO', 'OUT', datetime.time(11, 0), datetime.time(13, 0)),
    ('AI', 'IN', datetime.time(12, 0), datetime.time(15, 0)),
    ('AO', 'OUT', datetime.time(15, 0), datetime.time(23, 59, 59)),
]

def get_next_log_type(face):
    """
    Determines the next valid attendance log type based on state progression and time windows.
    Returns (log_type, error_message).
    """
    current_time = timezone.now().astimezone(MANILA_TZ)
    current_date = current_time.date()
    current_clock = current_time.time()
    
    log_sequence = ['MI', 'MO', 'AI', 'AO']
    
    # Fetch today's logs for this username (covers all enrolled faces for this person)
    today_logs = AttendanceLog.objects.filter(
        username=face.username,
        timestamp__date=current_date
    ).order_by('timestamp')
    
    last_log = today_logs.last()
    last_type = last_log.log_type if last_log else None
    
    last_index = -1
    if last_type in log_sequence:
        last_index = log_sequence.index(last_type)
    
    if last_index == len(log_sequence) - 1:
        return None, "You already completed attendance for today"
    
    # Check for duplicate action if we are very close to last log (e.g. within 1 minute)
    if last_log:
        time_diff = (current_time - last_log.timestamp).total_seconds()
        if time_diff < 60: # 1 minute threshold
            last_time_str = last_log.timestamp.astimezone(MANILA_TZ).strftime("%I:%M %p")
            return None, f"Already logged at {last_time_str}"

    for i in range(last_index + 1, len(log_sequence)):
        type_code = log_sequence[i]
        window = next((w for w in ATTENDANCE_WINDOWS if w[0] == type_code), None)
        _, action, start, end = window
        
        if start <= current_clock <= end:
            return type_code, None
        
        if current_clock < start:
            # We are before the NEXT valid window in sequence
            if last_log:
                last_time_str = last_log.timestamp.astimezone(MANILA_TZ).strftime("%I:%M %p")
                action_text = "timed in" if last_log.action == 'IN' else "timed out"
                return None, f"Already {action_text} at {last_time_str}"
            else:
                return None, "Attendance window has not opened yet"
                
    return None, "No active attendance window at this time"
