"""
Serializers for the survey app's GET / submit APIs.
"""

from rest_framework import serializers

from .models import SurveyResponse


class SurveyAnswerItemSerializer(serializers.Serializer):
    """One {question, answer} pair from the form."""

    question = serializers.CharField(allow_blank=False)
    # Free-text (question 5) can legitimately be blank; rating
    # questions are checked for non-null in the view before this
    # serializer ever runs, since "unanswered" there is a hard error.
    answer = serializers.CharField(allow_null=True, allow_blank=True, required=False)


class SurveySubmitSerializer(serializers.Serializer):
    """Validates the POST body sent to the submit endpoint."""

    course_id = serializers.CharField()
    survey_id = serializers.CharField()
    skip_survey = serializers.BooleanField(default=False)
    answers = SurveyAnswerItemSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs.get("skip_survey"):
            answers = attrs.get("answers")
            if not answers:
                raise serializers.ValidationError(
                    {"answers": "answers are required when skip_survey is false."}
                )
        return attrs


class SurveyResponseSerializer(serializers.ModelSerializer):
    """Read-only representation used by the GET (status) endpoint."""

    course_id = serializers.CharField()

    class Meta:
        model = SurveyResponse
        fields = [
            "id",
            "user_id",
            "course_id",
            "survey_id",
            "response_json",
            "skipped",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields