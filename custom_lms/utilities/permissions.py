# custom_lms/apps/cmu_dashboard/permissions.py
from rest_framework.permissions import BasePermission
from lms.djangoapps.courseware.access import has_access
from opaque_keys.edx.keys import CourseKey


class IsInstructorOrAdmin(BasePermission):
    def has_permission(self, request, view):
        course_id = request.query_params.get('course_id') or view.kwargs.get('course_id')
        if not course_id:
            return False
        course_key = CourseKey.from_string(course_id)
        user = request.user
        return (
            user.is_staff
            or bool(has_access(user, 'instructor', course_key))
            or bool(has_access(user, 'staff', course_key))
        )