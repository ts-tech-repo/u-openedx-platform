# custom_lms/apps.py

from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class CustomLmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "custom_lms"

    def ready(self):
        import custom_lms.admin  # noqa: F401 — registers all admin classes

        # --- Monkey-patch Course Tabs ---
        try:
            from lms.djangoapps.courseware import tabs as courseware_tabs
            from custom_lms.utils.tabs import AdminViewTab

            # Keep a reference to the original core function
            original_get_course_tab_list = courseware_tabs.get_course_tab_list
            logger.info("Tab List: %s", original_get_course_tab_list)

            def patched_get_course_tab_list(user, course):
                # 1. Get the default tabs from core
                tabs = original_get_course_tab_list(user, course)
                
                # 2. Check if the current user is allowed to see our custom tab
                if AdminViewTab.is_enabled(course, user):
                    # 3. Instantiate our custom tab
                    admin_tab = AdminViewTab({'type': 'admin_view'})
                    
                    # 4. Find the index of the 'instructor' tab
                    instructor_index = next((i for i, tab in enumerate(tabs) if tab.type == 'instructor'), -1)
                    
                    # 5. Insert our tab exactly after the instructor tab
                    if instructor_index != -1:
                        tabs.insert(instructor_index + 1, admin_tab)
                    else:
                        # Fallback: append to the end if instructor tab isn't found
                        tabs.append(admin_tab)
                        
                return tabs

            # 6. Replace the core function with our patched version
            courseware_tabs.get_course_tab_list = patched_get_course_tab_list
            logger.info("Successfully patched courseware tabs to include AdminViewTab.")
            
        except Exception as e:
            logger.error(f"Failed to patch courseware tabs in custom_lms: {e}")