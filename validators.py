from models import Artifact, TransitionLog, db
from datetime import datetime, timedelta
import re


# ────────────────────────────────────────────────
#  Configuration
# ────────────────────────────────────────────────
STAGES = [
    "Requirement",
    "Design",
    "Implementation",
    "Testing",
    "Release"
]

REQUIRED_ARTIFACTS = {
    "Requirement":    ["Requirement Document", "Stakeholder Approval"],
    "Design":         ["High-Level Design Document", "Architecture Diagram", "Data Model"],
    "Implementation": ["Source Code Reference", "Unit Test Coverage Report", "API Specification"],
    "Testing":        ["Test Plan", "Test Cases", "Test Execution Report", "Defect Summary"],
    "Release":        ["Release Notes", "Deployment Checklist", "Production Approval Record"]
}

# Which artifacts require structured/validated reference
ARTIFACT_QUALITY_RULES = {
    "Source Code Reference":      r"^[0-9a-f]{40}$|^[0-9a-f]{7}$",   # full or short git commit
    "Unit Test Coverage Report":  r"^https?://",
    "API Specification":          r"^https?://",
    "Release Notes":              r"^https?://",
    "Deployment Checklist":       r"^https?://",
    # "Requirement Document":     no rule → reference optional
    # "Stakeholder Approval":     no rule → reference optional
}

STAGE_TIMEOUT_DAYS = {
    "Requirement": 7,
    "Design": 10,
    "Implementation": 14,
    "Testing": 7,
    "Release": 3
}

MIN_REGRESSION_REASON_LENGTH = 30
MAX_ALLOWED_REGRESSIONS      = 3
MAX_ALLOWED_TRANSITIONS      = 20

WEAK_REASON_INDICATORS = {"fixed", "ok", "done", "bug", "error", "oops", "typo", "???", "whatever"}

# Which stages require special role to *leave* them
REQUIRED_APPROVER_ROLES = {
    "Requirement": ["Architect", "Admin", "Manager"],
    "Design": ["Architect", "Admin", "Manager"],
    "Implementation": ["Developer", "Admin", "Manager"],
    "Testing": ["Tester", "Admin", "Manager"],
    "Release": ["Manager", "Admin"]
}


def is_valid_stage(stage: str) -> bool:
    return stage in STAGES


def get_stage_index(stage: str) -> int:
    return STAGES.index(stage) if is_valid_stage(stage) else -1


def get_required_artifacts(stage: str) -> list[str]:
    return REQUIRED_ARTIFACTS.get(stage, [])


def count_regressions(work_item) -> int:
    logs = TransitionLog.query.filter_by(work_item_id=work_item.id).all()
    count = 0
    for i in range(1, len(logs)):
        if get_stage_index(logs[i].to_stage) < get_stage_index(logs[i-1].to_stage):
            count += 1
    return count


def count_total_transitions(work_item) -> int:
    return TransitionLog.query.filter_by(work_item_id=work_item.id).count()


def get_time_in_current_stage(work_item) -> timedelta:
    last_entry = TransitionLog.query.filter_by(
        work_item_id=work_item.id,
        to_stage=work_item.current_stage
    ).order_by(TransitionLog.transitioned_at.desc()).first()

    start = last_entry.transitioned_at if last_entry else work_item.created_at
    return datetime.utcnow() - start


def was_stage_exited(work_item, stage: str) -> bool:
    """
    True if there is ANY record of leaving this stage in history.
    More robust than checking only the most recent log.
    """
    return db.session.query(TransitionLog).filter(
        TransitionLog.work_item_id == work_item.id,
        TransitionLog.from_stage == stage
    ).first() is not None


def is_stage_locked(work_item, stage: str) -> tuple[bool, str]:
    """
    Artifact immutability rule:
    Once the stage was left at least once → no more artifacts allowed in it.
    """
    if stage != work_item.current_stage:
        return True, f"Cannot modify past stage '{stage}'. Current stage is '{work_item.current_stage}'."

    if was_stage_exited(work_item, stage):
        return True, f"Stage '{stage}' has already been exited — artifacts are now immutable."

    return False, "Stage still active — can add artifacts"


def has_duplicate_artifact(work_item, stage: str, artifact_type: str) -> bool:
    return Artifact.query.filter_by(
        work_item_id=work_item.id,
        stage=stage,
        artifact_type=artifact_type
    ).count() >= 1   # changed to 1 — most types should appear only once


def validate_artifact_quality(artifact_type: str, reference: str | None = None) -> tuple[bool, str]:
    """
    Enforce reference format ONLY for artifact types that have a quality rule.
    For others → reference is optional.
    """
    if artifact_type not in ARTIFACT_QUALITY_RULES:
        return True, "No quality rule — reference optional"

    if not reference or not reference.strip():
        return False, f"Reference is required for artifact type '{artifact_type}'"

    pattern = ARTIFACT_QUALITY_RULES[artifact_type]
    if not re.match(pattern, reference.strip()):
        return False, f"Invalid format for '{artifact_type}'. Expected pattern: {pattern}"

    return True, "Reference format valid"


def validate_stage_approval(current_stage: str, user_role: str | None) -> tuple[bool, str]:
    """
    Check if current user has permission to approve transition FROM this stage.
    """
    if not user_role:
        return False, "User role is required to transition stages in Enterprise mode."
        
    required_roles = REQUIRED_APPROVER_ROLES.get(current_stage)
    if not required_roles:
        return True, "No special approval required"

    if user_role not in required_roles:
        return False, f"Unauthorized: Only {', '.join(required_roles)} can approve transition from '{current_stage}'"

    return True, "Approval role verified"


def validate_transition(
    work_item,
    target_stage: str,
    regression_reason: str | None = None,
    user_role: str | None = None,
    requester_id: int | None = None
) -> tuple[bool, str, dict]:
    # Strictly block if requester is not the owner (unless Admin)
    # Note: requester_id equality check is requested specifically
    if work_item.owner_id is not None and requester_id is not None:
        if int(requester_id) != int(work_item.owner_id) and user_role != "Admin":
            return False, "FORBIDDEN: Only the workspace owner can request a stage transition.", {}

    if not is_valid_stage(target_stage):
        return False, f"Invalid stage: {target_stage}", {}

    current_stage = work_item.current_stage
    curr_idx = get_stage_index(current_stage)
    targ_idx = get_stage_index(target_stage)

    if curr_idx == -1 or targ_idx == -1:
        return False, "Internal stage error", {}

    if curr_idx == targ_idx:
        return False, f"Already in stage '{current_stage}'", {}

    extra = {
        "regression_count": count_regressions(work_item),
        "total_transitions": count_total_transitions(work_item)
    }

    if extra["total_transitions"] >= MAX_ALLOWED_TRANSITIONS:
        return False, f"Work item has reached maximum transitions ({MAX_ALLOWED_TRANSITIONS}).", extra

    # Forward transition
    if targ_idx == curr_idx + 1:
        complete, missing = check_artifacts_complete(work_item, current_stage)
        if not complete:
            return False, f"Cannot advance: missing {', '.join(missing)}", extra

        approval_ok, approval_msg = validate_stage_approval(current_stage, user_role)
        if not approval_ok:
            return False, approval_msg, extra

        # Overdue warning (non-blocking)
        days_in_stage = get_time_in_current_stage(work_item).days
        timeout = STAGE_TIMEOUT_DAYS.get(current_stage, 0)
        if timeout > 0 and days_in_stage > timeout:
            extra["warning"] = f"Warning: stage '{current_stage}' is overdue ({days_in_stage - timeout} days)"

        return True, f"Transition to '{target_stage}' approved.", extra

    if targ_idx > curr_idx + 1:
        return False, f"Stage skipping not allowed. Next allowed stage: {STAGES[curr_idx + 1]}", extra

    # Regression
    if targ_idx < curr_idx:
        if user_role not in ["Manager", "Admin"]:
            return False, "Unauthorized: Only Managers or Admins can approve a regression.", extra
            
        if extra["regression_count"] >= MAX_ALLOWED_REGRESSIONS:
            return False, f"Maximum regressions ({MAX_ALLOWED_REGRESSIONS}) reached.", extra

        if not regression_reason or not regression_reason.strip():
            return False, "Regression justification is required.", extra

        reason = regression_reason.strip()
        if len(reason) < MIN_REGRESSION_REASON_LENGTH:
            return False, f"Reason must be at least {MIN_REGRESSION_REASON_LENGTH} characters.", extra

        weak = [w for w in WEAK_REASON_INDICATORS if w in reason.lower()]
        if weak:
            extra["warning"] = f"Weak regression reason keywords: {', '.join(weak)}"

        return True, f"Regression allowed (#{extra['regression_count'] + 1}).", extra

    return False, "Invalid transition direction", extra


def check_artifacts_complete(work_item, for_stage: str | None = None) -> tuple[bool, list[str]]:
    stage = for_stage or work_item.current_stage
    required = get_required_artifacts(stage)
    if not required:
        return True, []

    present = {a.artifact_type for a in Artifact.query.filter_by(
        work_item_id=work_item.id,
        stage=stage
    ).all()}

    missing = [r for r in required if r not in present]
    return len(missing) == 0, missing


def can_add_artifact(
    work_item,
    stage: str,
    artifact_type: str,
    reference: str | None = None
) -> tuple[bool, str]:
    locked, reason = is_stage_locked(work_item, stage)
    if locked:
        return False, reason

    if has_duplicate_artifact(work_item, stage, artifact_type):
        return False, f"Artifact of type '{artifact_type}' already exists in stage '{stage}'."

    quality_ok, quality_msg = validate_artifact_quality(artifact_type, reference)
    if not quality_ok:
        return False, quality_msg

    return True, "Artifact can be added"