"""
Certificate eligibility checks for custom_lms.

Per the PRD: a learner is eligible for their certificate once they've
scored at least the configured passing score on every graded subsection
defined in the course's GRADER policy.
"""

import logging
from typing import Tuple, Dict, List, Any

from opaque_keys.edx.keys import CourseKey
from lms.djangoapps.courseware.courses import get_course_by_id

log = logging.getLogger(__name__)


def _as_course_key(course_id: str | CourseKey) -> CourseKey:
    """Convert a course ID into a CourseKey."""
    if isinstance(course_id, CourseKey):
        return course_id
    return CourseKey.from_string(str(course_id))


def _get_grader_policies(course: Any) -> List[Dict]:
    """Return all GRADER entries from the course grading policy."""
    grading_policy = getattr(course, "grading_policy", None) or {}
    grader_policies = grading_policy.get("GRADER", [])

    if not isinstance(grader_policies, list):
        log.warning(
            "Invalid GRADER grading policy. Expected list, got %s",
            type(grader_policies).__name__,
        )
        return []

    return grader_policies


def _get_grader_policy_by_type(course: Any) -> Dict[str, Dict]:
    """
    Build a mapping of assignment type -> GRADER policy.
    
    Matching is case-insensitive. If duplicate types exist in the 
    grading policy, the last entry wins.
    
    Example:
        {
            "knowledge check": {...},
            "assignment": {...},
            "quiz": {...},
        }
    """
    policies_by_type = {}
    for policy in _get_grader_policies(course):
        if not isinstance(policy, dict):
            continue
        
        assignment_type = str(policy.get("type", "")).strip()
        if assignment_type:
            policies_by_type[assignment_type.lower()] = policy

    return policies_by_type


def _get_default_passing_score(course: Any) -> float:
    """
    Get the course-wide passing score from GRADE_CUTOFFS["Pass"].
    
    Returns:
        float: The default passing score.
    """
    grading_policy = getattr(course, "grading_policy", None) or {}
    grade_cutoffs = grading_policy.get("GRADE_CUTOFFS", {}) or {}

    try:
        return float(grade_cutoffs.get("Pass", 0.0))
    except (TypeError, ValueError):
        raise ValueError("Invalid GRADE_CUTOFFS['Pass'] value")


def _get_passing_score(course: Any, grader_policy: Dict) -> float:
    """
    Determine the passing score for a graded assignment type.
    
    Resolution order:
        1. GRADER["min_passing_score"]
        2. GRADE_CUTOFFS["Pass"]
        
    Returns:
        float: The passing score for the assignment type.
    """
    per_type_score = grader_policy.get("min_passing_score")
    if per_type_score is not None:
        return float(per_type_score)
    
    return _get_default_passing_score(course)


def _get_subsection_percent(subsection_grade: Any) -> float:
    """
    Get the learner's percentage for a subsection.
    Prefers `percent_graded`, falling back to `earned_graded / possible_graded`.
    
    Returns:
        float: The learner's percentage (0.0 to 1.0).
    """
    percent = getattr(subsection_grade, "percent_graded", None)
    if percent is not None:
        return float(percent)

    possible = float(getattr(subsection_grade, "possible_graded", 0) or 0)
    earned = float(getattr(subsection_grade, "earned_graded", 0) or 0)

    if not possible:
        return 0.0

    return earned / possible


def is_eligible_for_certificate(user: Any, course_id: str | CourseKey) -> Tuple[bool, Dict]:
    """
    Check whether a learner is eligible for their certificate.

    A learner is eligible when:
        1. The course can be loaded.
        2. The course has at least one GRADER entry.
        3. The learner's course grade can be loaded.
        4. Every graded subsection configured in the GRADER policy meets its applicable passing score.

    IMPORTANT: This function does NOT assume that the graded content is a "Knowledge Check".
    Any subsection whose `format` matches a GRADER `type` is considered.

    Returns:
        tuple: (eligible: bool, details: dict)
    """
    from lms.djangoapps.grades.api import CourseGradeFactory

    course_key = _as_course_key(course_id)

    # 1. Load course
    try:
        course = get_course_by_id(course_key)
        grading_policy = getattr(course, "grading_policy", None) or {}
        log.info("Course grading policy for course_id=%s: %s", course_key, grading_policy)
    except Exception:
        log.exception("Unable to load course for user_id=%s course_id=%s", user.id, course_key)
        return False, {
            "graded_subsections": [],
            "minimum_score": 0.0,
            "error": "course_unavailable",
        }

    # 2. Get GRADER policies
    grader_policies = _get_grader_policies(course)
    if not grader_policies:
        log.warning("No GRADER assignment types configured in grading policy for course_id=%s", course_key)
        return False, {
            "graded_subsections": [],
            "minimum_score": 0.0,
            "error": "grader_policy_not_configured",
        }

    # 3. Build assignment-type lookup
    grader_policies_by_type = _get_grader_policy_by_type(course)
    if not grader_policies_by_type:
        log.warning("GRADER policy contains no valid assignment types for course_id=%s", course_key)
        return False, {
            "graded_subsections": [],
            "minimum_score": 0.0,
            "error": "grader_policy_not_configured",
        }

    log.info("Graded assignment types for course_id=%s: %s", course_key, list(grader_policies_by_type.keys()))

    # 4. Get default course-wide passing score
    try:
        default_minimum_score = _get_default_passing_score(course)
    except (TypeError, ValueError):
        log.exception("Invalid Pass cutoff in grading policy for course_id=%s", course_key)
        return False, {
            "graded_subsections": [],
            "minimum_score": 0.0,
            "error": "invalid_pass_cutoff",
        }

    log.info("Course-wide passing score: course_id=%s minimum_score=%s", course_key, default_minimum_score)

    # 5. Load learner course grade
    try:
        course_grade = CourseGradeFactory().read(user, course_key=course_key)
        log.info("Loaded course grade for user_id=%s course_id=%s", user.id, course_key)
    except Exception:
        log.exception("Unable to load course grade for user_id=%s course_id=%s", user.id, course_key)
        return False, {
            "graded_subsections": [],
            "minimum_score": float(default_minimum_score),
            "error": "grade_unavailable",
        }

    # 6. Check every graded subsection
    graded_subsections = []
    all_passed = True

    log.info("Checking subsection grades for user_id=%s course_id=%s", user.id, course_key)

    for subsection_grade in course_grade.subsection_grades.values():
        if not getattr(subsection_grade, "graded", False):
            continue

        subsection_format = str(getattr(subsection_grade, "format", "") or "").strip()
        display_name = str(getattr(subsection_grade, "display_name", "") or "").strip()

        log.info(
            "Subsection: display_name=%s format=%s graded=%s",
            display_name,
            subsection_format,
            getattr(subsection_grade, "graded", False),
        )

        if not subsection_format:
            log.info("Skipping graded subsection with no assignment type: display_name=%s", display_name)
            continue

        # Find matching GRADER policy
        grader_policy = grader_policies_by_type.get(subsection_format.lower())
        if not grader_policy:
            log.info(
                "Skipping graded subsection because its format is not configured in GRADER: "
                "display_name=%s format=%s",
                display_name,
                subsection_format,
            )
            continue

        # Determine passing score for this assignment type
        try:
            minimum_score = _get_passing_score(course, grader_policy)
        except (TypeError, ValueError):
            log.exception(
                "Invalid passing score for assignment type=%s course_id=%s",
                subsection_format,
                course_key,
            )
            return False, {
                "graded_subsections": graded_subsections,
                "minimum_score": float(default_minimum_score),
                "error": "invalid_pass_cutoff",
            }

        # Validate passing score
        if not 0.0 <= minimum_score <= 1.0:
            log.error(
                "Passing score is outside valid range [0, 1]: assignment_type=%s minimum_score=%s course_id=%s",
                subsection_format,
                minimum_score,
                course_key,
            )
            return False, {
                "graded_subsections": graded_subsections,
                "minimum_score": float(default_minimum_score),
                "error": "invalid_pass_cutoff",
            }

        # Calculate learner percentage
        try:
            percent = _get_subsection_percent(subsection_grade)
        except (TypeError, ValueError, ZeroDivisionError):
            log.exception("Unable to calculate percentage for subsection=%s course_id=%s", display_name, course_key)
            percent = 0.0

        # Convert NumPy values to native Python types to prevent JSON serialization errors
        percent = float(percent)
        passed = bool(percent >= minimum_score)

        if not passed:
            all_passed = False

        graded_subsections.append({
            "display_name": display_name,
            "format": subsection_format,
            "percent": float(round(percent * 100, 1)),
            "minimum_score": float(round(minimum_score * 100, 1)),
            "passed": bool(passed),
        })

        log.info(
            "Graded subsection: name=%s format=%s score=%.2f%% minimum=%.2f%% passed=%s",
            display_name,
            subsection_format,
            percent * 100,
            minimum_score * 100,
            passed,
        )

    # 7. Final eligibility
    # Fail closed when the course contains no matching graded subsections.
    eligible = bool(graded_subsections and all_passed)

    log.info(
        "Certificate eligibility: user_id=%s course_id=%s eligible=%s graded_subsections=%s",
        user.id,
        course_key,
        eligible,
        len(graded_subsections),
    )

    # 8. Backward-compatible response fields
    return eligible, {
        "graded_subsections": graded_subsections,
        "knowledge_checks": graded_subsections,  # Backward compatibility for existing callers
        "minimum_score": float(default_minimum_score),
    }