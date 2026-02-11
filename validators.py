from models import Artifact

STAGES = [
    "Requirement",
    "Design",
    "Implementation",
    "Testing",
    "Release"
]

REQUIRED_ARTIFACTS = {
    "Requirement": ["Requirement Document"],
    "Design": ["Design Document"],
    "Implementation": ["Source Code Reference"],
    "Testing": ["Test Report"],
    "Release": []
}

def get_stage_index(stage_name):
    if stage_name in STAGES:
        return STAGES.index(stage_name)
    return -1

def validate_transition(work_item, target_stage, regression_reason=None):
    if target_stage not in STAGES:
        return False, "Invalid SDLC stage."

    current_index = get_stage_index(work_item.current_stage)
    target_index = get_stage_index(target_stage)

    if current_index == -1 or target_index == -1:
        return False, "Invalid stage name."

    if current_index == target_index:
        return False, "Work item is already in this stage."

    if target_index == current_index + 1:
        required = REQUIRED_ARTIFACTS.get(work_item.current_stage, [])
        for artifact_type in required:
            exists = Artifact.query.filter_by(
                work_item_id=work_item.id,
                stage=work_item.current_stage,
                artifact_type=artifact_type
            ).first()
            if not exists:
                return False, f"Missing required artifact: {artifact_type}"
        return True, "Forward transition allowed."

    if target_index > current_index + 1:
        return False, "Stage skipping is not allowed."

    if target_index < current_index:
        if not regression_reason or not regression_reason.strip():
            return False, "Regression requires a justification reason."
        return True, "Regression allowed with justification."

    return False, "Invalid stage transition."