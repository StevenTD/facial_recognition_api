from django.contrib import admin
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
    list_display = ('username', 'action', 'timestamp', 'get_captured_image')
    list_filter = ('action', 'timestamp', 'face')
    search_fields = ('username',)
    readonly_fields = ('get_captured_image',)

    def get_captured_image(self, obj):
        if obj.captured_image:
            return format_html('<img src="{}" width="50" height="50" style="border-radius: 50%;" />', obj.captured_image.url)
        return "No Image"
    get_captured_image.short_description = 'Captured Face preview'


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
