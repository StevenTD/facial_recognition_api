from django.contrib import admin, messages
from django.urls import path
from django.shortcuts import redirect, get_object_or_404
from django.utils.html import format_html
from .models import User, Face, AttendanceLog, WebhookConfig

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'is_staff', 'created_at')

@admin.register(Face)
class FaceAdmin(admin.ModelAdmin):
    list_display = ('username', 'get_face_image', 'user', 'created_at')
    readonly_fields = ('get_face_image',)

    def get_face_image(self, obj):
        if obj.face_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.face_image.url)
        return "No Image"
    get_face_image.short_description = 'Face Image preview'

@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('username', 'log_type_badge', 'action', 'timestamp', 'frappe_status', 'submit_button', 'get_captured_image')
    list_filter = ('action', 'log_type', 'frappe_synced', 'timestamp', 'face')
    search_fields = ('username',)
    readonly_fields = ('get_captured_image', 'frappe_synced', 'frappe_error')
    actions = ['submit_to_frappe_hrms']

    def log_type_badge(self, obj):
        colors = {'MI': '#4caf50', 'MO': '#ff9800', 'AI': '#2196f3', 'AO': '#9c27b0'}
        if obj.log_type:
            color = colors.get(obj.log_type, '#999')
            return format_html(
                '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold">{}</span>',
                color, obj.get_log_type_display()
            )
        return '—'
    log_type_badge.short_description = 'Log Type'

    def frappe_status(self, obj):
        if obj.frappe_synced:
            return format_html(
                '<span style="background:#4caf50;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">'
                '✓ Synced</span>'
            )
        elif obj.frappe_error:
            return format_html(
                '<span style="background:#f44336;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px" '
                'title="{}">'
                '✗ Failed</span>',
                obj.frappe_error[:200]
            )
        else:
            return format_html(
                '<span style="background:#9e9e9e;color:#fff;padding:2px 8px;border-radius:4px;font-size:11px">'
                '⏳ Pending</span>'
            )
    frappe_status.short_description = 'Frappe Sync'

    def submit_button(self, obj):
        """Render a clickable Submit / Re-submit button directly in the list row."""
        if obj.frappe_synced:
            return format_html(
                '<a href="submit-to-frappe/{}/" '
                'style="background:#ff9800;color:#fff;padding:4px 12px;border-radius:4px;'
                'font-size:11px;text-decoration:none;white-space:nowrap">'
                '🔄 Re-submit</a>',
                obj.pk
            )
        else:
            return format_html(
                '<a href="submit-to-frappe/{}/" '
                'style="background:#2196f3;color:#fff;padding:4px 12px;border-radius:4px;'
                'font-size:11px;text-decoration:none;white-space:nowrap">'
                '📤 Submit</a>',
                obj.pk
            )
    submit_button.short_description = 'Frappe Action'

    def get_captured_image(self, obj):
        if obj.captured_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.captured_image.url)
        return "No Image"
    get_captured_image.short_description = 'Captured Face preview'

    def get_urls(self):
        """Add a custom URL for the per-row submit button."""
        custom_urls = [
            path(
                'submit-to-frappe/<int:log_id>/',
                self.admin_site.admin_view(self.submit_single_to_frappe),
                name='face_attendancelog_submit_frappe',
            ),
        ]
        return custom_urls + super().get_urls()

    def submit_single_to_frappe(self, request, log_id):
        """Handle a single-log submit button click from the list view."""
        from . import handlers as h

        log = get_object_or_404(AttendanceLog, pk=log_id)
        ok, msg = h.submit_log_to_frappe(log)

        if ok:
            self.message_user(request, msg, level=messages.SUCCESS)
        else:
            self.message_user(request, msg, level=messages.ERROR)

        # Redirect back to the list (preserving any filters the user had)
        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        return redirect('..')

    def submit_to_frappe_hrms(self, request, queryset):
        """Admin action: retry submitting selected logs to Frappe HRMS."""
        from . import handlers as h

        success_count = 0
        fail_count = 0
        msgs = []

        for log in queryset:
            ok, msg = h.submit_log_to_frappe(log)
            if ok:
                success_count += 1
            else:
                fail_count += 1
            msgs.append(msg)

        if success_count and not fail_count:
            self.message_user(request, f"✓ Successfully synced {success_count} log(s) to Frappe HRMS.", level=messages.SUCCESS)
        elif fail_count and not success_count:
            self.message_user(request, f"✗ Failed to sync {fail_count} log(s). Check error details on each record.", level=messages.ERROR)
        else:
            self.message_user(
                request,
                f"Synced {success_count}, failed {fail_count}. Details: {'; '.join(msgs[:5])}",
                level=messages.WARNING,
            )
    submit_to_frappe_hrms.short_description = "📤 Submit selected to Frappe HRMS"


@admin.register(WebhookConfig)
class WebhookConfigAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'method', 'log_types_display', 'is_enabled', 'updated_at')
    list_filter = ('method', 'is_enabled')
    search_fields = ('name', 'url')
    list_editable = ('is_enabled',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Endpoint', {
            'fields': ('name', 'url', 'method', 'timeout')
        }),
        ('Trigger', {
            'description': "Which log types should fire this webhook. Use comma-separated codes: MI, MO, AI, AO",
            'fields': ('log_types', 'is_enabled'),
        }),
        ('Auth / Headers', {
            'classes': ('collapse',),
            'fields': ('custom_headers',),
        }),
        ('Timestamps', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def log_types_display(self, obj):
        colors = {'MI': '#4caf50', 'MO': '#ff9800', 'AI': '#2196f3', 'AO': '#9c27b0'}
        badges = ''
        for t in [x.strip() for x in obj.log_types.split(',') if x.strip()]:
            color = colors.get(t, '#999')
            badges += format_html(
                '<span style="background:{};color:#fff;padding:2px 6px;border-radius:4px;margin-right:3px;font-size:11px">{}</span>',
                color, t
            )
        return format_html(badges) if badges else '—'
    log_types_display.short_description = 'Triggers On'
