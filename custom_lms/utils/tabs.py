# custom_lms/utils/tabs.py

from lms.djangoapps.courseware.tabs import LinkTab
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole

class AdminViewTab(LinkTab):
    """
    Custom Course Tab for the Admin View MFE.
    Inherits from LinkTab to easily handle external MFE URLs.
    """
    type = 'admin_view'
    name = _('Admin View')
    title = _('Admin View')
    
    # Priority determines default sort order. 
    # Instructor tab is usually priority 100. We set this to 105 as a fallback.
    priority = 105 

    @classmethod
    def is_enabled(cls, course, user=None):
        """
        Backend permission check. 
        Hides the tab completely from standard enrolled students.
        """
        if not user or user.is_anonymous:
            return False
        
        # Allow global staff/admins
        if user.is_staff:
            return True
            
        # Allow course-specific staff and instructors
        return (
            CourseStaffRole(course.id).has_user(user) or 
            CourseInstructorRole(course.id).has_user(user)
        )

    def __init__(self, tab_dict):
        # Dynamically inject the MFE URL using the base LMS URL
        base_url = getattr(settings, 'LMS_ROOT_URL', '')
        tab_dict['link'] = f"{base_url}/course-admin-view/{tab_dict.get('course_id', '')}/"
        tab_dict['name'] = str(self.name)
        tab_dict['type'] = self.type
        
        # Initialize the parent LinkTab
        super().__init__(tab_dict)