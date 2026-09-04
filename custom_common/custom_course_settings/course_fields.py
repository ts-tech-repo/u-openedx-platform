from collections import OrderedDict

from django.utils.translation import gettext_lazy as _
from xblock.fields import Boolean, Scope

from xmodule.course_block import CourseBlock, CourseFields


FIELD_NAME = "enable_certificate"


def register_enable_certificate_field():
    return
    """
    Register enable_certificate as a CourseFields/CourseBlock setting.

    The field is inserted immediately after advanced_modules so that the
    existing Advanced Settings UI renders it directly below
    "Advanced Module List".
    """

    if FIELD_NAME in CourseBlock.fields:
        return

    field = Boolean(
        display_name=_("Custom Certificate"),
        help=_(
            "If enabled, learners who satisfy the course certificate "
            "requirements can receive a certificate."
        ),
        default=True,
        scope=Scope.settings,
    )

    # Add the field to CourseFields so CourseBlock instances can expose it.
    setattr(CourseFields, FIELD_NAME, field)

    # Add the field to CourseBlock as well.
    setattr(CourseBlock, FIELD_NAME, field)

    # Preserve the existing field order and insert our field immediately
    # after "advanced_modules".
    fields = OrderedDict()

    for name, existing_field in CourseBlock.fields.items():
        fields[name] = existing_field

        if name == "advanced_modules":
            fields[FIELD_NAME] = field

    CourseBlock.fields = dict(fields)