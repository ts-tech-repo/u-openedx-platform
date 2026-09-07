"""
Serializers for the admin-view models: AvLearners, AvSummary, AvSyncHistory.
"""

from rest_framework import serializers

from ..models.admin_view import AvLearners, AvSummary, AvSyncHistory


class AvLearnersSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for the per-learner cache row.
    `course_id` and `user_id` are exposed as plain strings/ints so the
    payload stays JSON-safe without any extra opaque-key handling on the
    client side.
    """

    course_id = serializers.CharField(read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = AvLearners
        fields = [
            "id",
            "user_id",
            "username",
            "email",
            "course_id",
            "name",
            "enrolled_on",
            "course_progress",
            "checkpoints_completed",
            "checkpoints_total",
            "last_login",
            "program_status",
        ]
        read_only_fields = fields


class AvSummarySerializer(serializers.ModelSerializer):
    """
    Read-only serializer for the per-course aggregate cache row.
    """

    course_id = serializers.CharField(read_only=True)

    class Meta:
        model = AvSummary
        fields = [
            "id",
            "course_id",
            "enrolled_count",
            "in_progress_count",
            "completed_count",
            "completion_rate",
            "active_learners_count",
            "av_checkpoints_completed",
            "completed_checkpoints_total",
            "checkpoints_total",
        ]
        read_only_fields = fields


class AvSyncHistorySerializer(serializers.ModelSerializer):
    """
    Read-only serializer for sync-run audit rows.
    """

    duration_seconds = serializers.FloatField(allow_null=True, read_only=True)

    class Meta:
        model = AvSyncHistory
        fields = [
            "id",
            "started_at",
            "finished_at",
            "status",
            "trigger",
            "courses_processed",
            "courses_failed",
            "learners_processed",
            "duration_seconds",
            "error_message",
        ]
        read_only_fields = fields
