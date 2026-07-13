from django.urls import path
from . import views


urlpatterns = [
    path(
        "health/",
        views.health,
        name="custom-cms-health"
    ),
    
    path(
        "user/access/<str:enroll>",
        views.extras_course_enroll_user,
        name="custom-course-enroll-user"
    ),
]