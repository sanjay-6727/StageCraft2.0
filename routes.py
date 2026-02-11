from flask import request, jsonify, render_template
from models import db, WorkItem, Artifact, TransitionLog
from validators import validate_transition, STAGES, REQUIRED_ARTIFACTS

def register_routes(app):

    @app.route("/")
    def home():
        return {"message": "Stagecraft Backend Running Successfully 🚀"}

    @app.route("/ui/board")
    def ui_board():
        return render_template("board.html")

    @app.route("/ui/metrics")
    def ui_metrics():
        return render_template("metrics.html")

    @app.route("/workitems", methods=["GET"])
    def get_workitems():
        items = WorkItem.query.all()
        result = []
        for item in items:
            result.append({
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "current_stage": item.current_stage,
                "created_at": item.created_at.isoformat() if item.created_at else None
            })
        return jsonify(result)

    @app.route("/workitems", methods=["POST"])
    def create_workitem():
        data = request.get_json()
        if not data or "title" not in data:
            return jsonify({"error": "Title is required"}), 400

        item = WorkItem(
            title=data["title"],
            description=data.get("description", "")
        )
        db.session.add(item)
        db.session.commit()

        return jsonify({
            "message": "Work item created",
            "id": item.id
        }), 201

    @app.route("/workitems/<int:id>", methods=["GET"])
    def get_workitem_detail(id):
        work_item = WorkItem.query.get(id)
        if not work_item:
            return jsonify({"error": "Work item not found"}), 404

        artifacts = Artifact.query.filter_by(work_item_id=id).all()
        history = TransitionLog.query.filter_by(work_item_id=id).order_by(TransitionLog.transitioned_at.asc()).all()

        return jsonify({
            "id": work_item.id,
            "title": work_item.title,
            "description": work_item.description,
            "current_stage": work_item.current_stage,
            "created_at": work_item.created_at.isoformat() if work_item.created_at else None,
            "artifacts": [{"type": a.artifact_type, "stage": a.stage, "created_at": a.created_at.isoformat() if a.created_at else None} for a in artifacts],
            "history": [{"from": h.from_stage, "to": h.to_stage, "reason": h.reason, "timestamp": h.transitioned_at.isoformat() if h.transitioned_at else None} for h in history]
        })

    @app.route("/workitems/<int:id>/artifact", methods=["POST"])
    def add_artifact(id):
        work_item = WorkItem.query.get(id)
        if not work_item:
            return jsonify({"error": "Work item not found"}), 404

        data = request.get_json()
        if not data or "artifact_type" not in data:
            return jsonify({"error": "artifact_type is required"}), 400

        allowed_types = REQUIRED_ARTIFACTS.get(work_item.current_stage, [])

        if data["artifact_type"] not in allowed_types:
            return jsonify({"error": "Invalid artifact type for current stage", "current_stage": work_item.current_stage, "allowed_types": allowed_types}), 400

        artifact = Artifact(work_item_id=id, stage=work_item.current_stage, artifact_type=data["artifact_type"])
        db.session.add(artifact)
        db.session.commit()

        return jsonify({"message": "Artifact recorded", "artifact_id": artifact.id, "stage": artifact.stage, "type": artifact.artifact_type}), 201

    @app.route("/workitems/<int:id>/transition", methods=["POST"])
    def transition_stage(id):
        work_item = WorkItem.query.get(id)
        if not work_item:
            return jsonify({"error": "Work item not found"}), 404

        data = request.get_json()
        if not data or "target_stage" not in data:
            return jsonify({"error": "target_stage is required"}), 400

        target_stage = data["target_stage"]
        regression_reason = data.get("reason", "").strip()

        if target_stage not in STAGES:
            return jsonify({"error": "Invalid SDLC stage", "provided": target_stage, "valid_stages": STAGES}), 400

        allowed, message = validate_transition(work_item, target_stage, regression_reason)

        if not allowed:
            current_artifacts = [a.artifact_type for a in Artifact.query.filter_by(work_item_id=id, stage=work_item.current_stage).all()]
            required = REQUIRED_ARTIFACTS.get(work_item.current_stage, [])
            return jsonify({"blocked": True, "reason": message, "current_stage": work_item.current_stage, "target_stage": target_stage, "required_artifacts": required, "uploaded_artifacts": current_artifacts}), 400

        current_index = STAGES.index(work_item.current_stage)
        target_index = STAGES.index(target_stage)
        is_regression = target_index < current_index

        log = TransitionLog(work_item_id=id, from_stage=work_item.current_stage, to_stage=target_stage, reason=regression_reason if is_regression else None)
        work_item.current_stage = target_stage
        db.session.add(log)
        db.session.commit()

        return jsonify({"blocked": False, "message": "Stage updated successfully", "new_stage": target_stage})

    @app.route("/workitems/<int:id>/history", methods=["GET"])
    def get_history(id):
        work_item = WorkItem.query.get(id)
        if not work_item:
            return jsonify({"error": "Work item not found"}), 404

        logs = TransitionLog.query.filter_by(work_item_id=id).order_by(TransitionLog.transitioned_at.asc()).all()
        result = [{"from": log.from_stage, "to": log.to_stage, "reason": log.reason, "timestamp": log.transitioned_at.isoformat() if log.transitioned_at else None} for log in logs]

        return jsonify({"work_item_id": id, "current_stage": work_item.current_stage, "history": result})

    @app.route("/board", methods=["GET"])
    def stage_board():
        board = {}
        for stage in STAGES:
            items = WorkItem.query.filter_by(current_stage=stage).order_by(WorkItem.created_at.desc()).all()
            board[stage] = [{"id": item.id, "title": item.title, "description_snippet": item.description[:80] + "..." if item.description else ""} for item in items]
        return jsonify(board)

    @app.route("/metrics", methods=["GET"])
    def get_metrics():
        metrics_data = {stage: WorkItem.query.filter_by(current_stage=stage).count() for stage in STAGES}
        return jsonify({"items_per_stage": metrics_data, "total_items": WorkItem.query.count(), "total_stage_transitions": TransitionLog.query.count()})
