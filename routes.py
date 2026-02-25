from flask import request, jsonify, render_template, session, redirect, url_for
from functools import wraps
from models import db, WorkItem, Artifact, TransitionLog, Comment, CodeFile, User, Project
from validators import (
    validate_transition,
    can_add_artifact,
    check_artifacts_complete,
    STAGES,
    REQUIRED_ARTIFACTS,
    get_stage_index
)

def register_routes(app):

    # ────────────────────────────────────────────────
    #  1. Health / Root
    # ────────────────────────────────────────────────
    @app.route("/", methods=["GET"])
    def home():
        return jsonify({"message": "Stagecraft Backend Running Successfully 🚀"})


    # ────────────────────────────────────────────────
    #  2. Work Item CRUD
    # ────────────────────────────────────────────────
    @app.route("/workitems", methods=["POST"])
    def create_workitem():
        data = request.get_json(silent=True) or {}
        
        if not data.get("title"):
            return jsonify({"error": "title is required"}), 400

        work_item = WorkItem(
            title=data["title"],
            description=data.get("description", ""),
            current_stage="Requirement",  # explicit default
            priority=data.get("priority", "Medium"),
            assignee=data.get("assignee", "Unassigned")
        )
        
        db.session.add(work_item)
        db.session.commit()

        return jsonify({
            "message": "Work item created",
            "id": work_item.id,
            "stage": work_item.current_stage
        }), 201


    @app.route("/workitems", methods=["GET"])
    def list_workitems():
        items = WorkItem.query.order_by(WorkItem.created_at.desc()).all()
        
        return jsonify([
            {
                "id": w.id,
                "title": w.title,
                "current_stage": w.current_stage,
                "priority": w.priority,
                "assignee": w.assignee,
                "created_at": w.created_at.isoformat() if w.created_at else None
            }
            for w in items
        ])


    @app.route("/workitems/<int:id>", methods=["GET"])
    def get_workitem_detail(id):
        work_item = WorkItem.query.get_or_404(id)

        artifacts = Artifact.query.filter_by(work_item_id=id).order_by(Artifact.created_at).all()
        history = TransitionLog.query.filter_by(work_item_id=id).order_by(TransitionLog.transitioned_at).all()
        comments = Comment.query.filter_by(work_item_id=id).order_by(Comment.created_at.asc()).all()

        return jsonify({
            "id": work_item.id,
            "title": work_item.title,
            "description": work_item.description,
            "current_stage": work_item.current_stage,
            "priority": work_item.priority,
            "assignee": work_item.assignee,
            "created_at": work_item.created_at.isoformat() if work_item.created_at else None,
            "artifacts": [
                {
                    "type": a.artifact_type,
                    "stage": a.stage,
                    "reference": a.reference,
                    "created_at": a.created_at.isoformat() if a.created_at else None
                } for a in artifacts
            ],
            "history": [
                {
                    "from": h.from_stage,
                    "to": h.to_stage,
                    "reason": h.reason,
                    "timestamp": h.transitioned_at.isoformat() if h.transitioned_at else None
                } for h in history
            ],
            "comments": [c.to_dict() for c in comments]
        })


    # ────────────────────────────────────────────────
    #  3. Artifact Management
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/artifact", methods=["POST"])
    def add_artifact(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}

        artifact_type = data.get("artifact_type")
        reference     = data.get("reference")   # may be None/empty for some types

        if not artifact_type:
            return jsonify({"error": "artifact_type is required"}), 400

        allowed, message = can_add_artifact(
            work_item=work_item,
            stage=work_item.current_stage,
            artifact_type=artifact_type,
            reference=reference
        )

        if not allowed:
            return jsonify({
                "error": "Cannot add artifact",
                "reason": message
            }), 400

        # All checks passed → create
        artifact = Artifact(
            work_item_id=id,
            stage=work_item.current_stage,
            artifact_type=artifact_type,
            reference=reference.strip() if reference else None
        )

        db.session.add(artifact)
        db.session.commit()

        return jsonify({
            "message": "Artifact recorded",
            "artifact": {
                "id": artifact.id,
                "type": artifact.artifact_type,
                "stage": artifact.stage,
                "reference": artifact.reference,
                "created_at": artifact.created_at.isoformat()
            }
        }), 201


    # ────────────────────────────────────────────────
    #  3.5. Comment Management
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/comment", methods=["POST"])
    def add_comment(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        
        content = data.get("content")
        author = data.get("author", "User")

        if not content:
            return jsonify({"error": "content is required"}), 400

        comment = Comment(
            work_item_id=id,
            author=author,
            content=content
        )
        db.session.add(comment)
        db.session.commit()

        return jsonify({
            "message": "Comment added",
            "comment": comment.to_dict()
        }), 201


    # ────────────────────────────────────────────────
    #  3.6. Code push/pull Github-like integration
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/code", methods=["GET"])
    def get_code(id):
        work_item = WorkItem.query.get_or_404(id)
        files = CodeFile.query.filter_by(work_item_id=id).order_by(CodeFile.updated_at.desc()).all()
        return jsonify([f.to_dict() for f in files])

    @app.route("/workitems/<int:id>/code", methods=["POST"])
    def push_code(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        
        filename = data.get("filename")
        content = data.get("content", "")

        if not filename:
            return jsonify({"error": "filename is required"}), 400

        code_file = CodeFile.query.filter_by(work_item_id=id, filename=filename).first()
        if code_file:
            code_file.content = content
        else:
            code_file = CodeFile(work_item_id=id, filename=filename, content=content)
            db.session.add(code_file)
            
        db.session.commit()

        return jsonify({
            "message": "Code pushed successfully",
            "file": code_file.to_dict()
        }), 201


    # ────────────────────────────────────────────────
    #  4. Stage Transition (core enforcement point)
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/transition", methods=["POST"])
    def transition_stage(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}

        target_stage     = data.get("target_stage")
        regression_reason = data.get("reason", "").strip()
        user_role        = data.get("user_role")   # optional – can come from auth later

        if not target_stage:
            return jsonify({"error": "target_stage is required"}), 400

        allowed, message, extra = validate_transition(
            work_item=work_item,
            target_stage=target_stage,
            regression_reason=regression_reason if regression_reason else None,
            user_role=user_role
        )

        if not allowed:
            return jsonify({
                "blocked": True,
                "reason": message,
                "meta": extra
            }), 400

        # Transition is allowed → execute it
        log = TransitionLog(
            work_item_id=id,
            from_stage=work_item.current_stage,
            to_stage=target_stage,
            reason=regression_reason if get_stage_index(target_stage) < get_stage_index(work_item.current_stage) else None
        )

        work_item.current_stage = target_stage

        db.session.add(log)
        db.session.commit()

        return jsonify({
            "blocked": False,
            "message": message,
            "new_stage": target_stage,
            "meta": extra
        })


    # ────────────────────────────────────────────────
    #  4.5. DevOps / CI-CD Pipeline Simulation
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/pipeline/trigger", methods=["POST"])
    def trigger_pipeline(id):
        work_item = WorkItem.query.get_or_404(id)
        if work_item.current_stage != "Implementation":
            return jsonify({"error": "Pipeline can only be triggered in the Implementation stage"}), 400
            
        # Auto-supply all required Implementation artifacts to simulate a CI build
        if not Artifact.query.filter_by(work_item_id=id, stage="Implementation", artifact_type="Unit Test Coverage Report").first():
            db.session.add(Artifact(work_item_id=id, stage="Implementation", artifact_type="Unit Test Coverage Report", reference="https://ci.devops.internal/coverage/938", comment="Auto-generated by Jenkins CI"))
            
        if not Artifact.query.filter_by(work_item_id=id, stage="Implementation", artifact_type="Source Code Reference").first():
            db.session.add(Artifact(work_item_id=id, stage="Implementation", artifact_type="Source Code Reference", reference="fb881d3", comment="Auto-merged PR by GitHub Actions"))

        if not Artifact.query.filter_by(work_item_id=id, stage="Implementation", artifact_type="API Specification").first():
            db.session.add(Artifact(work_item_id=id, stage="Implementation", artifact_type="API Specification", reference="https://swagger.internal/auto", comment="Auto-generated Swagger spec"))
            
        # Auto-Transition to Testing
        log = TransitionLog(
            work_item_id=id,
            from_stage="Implementation",
            to_stage="Testing",
            reason=None
        )
        work_item.current_stage = "Testing"
        
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            "message": "CI/CD Pipeline Succeeded. Artifacts auto-generated and item moved straight to Testing.",
            "new_stage": "Testing"
        })
    # ────────────────────────────────────────────────
    @app.route("/board", methods=["GET"])
    def stage_board():
        board = {}
        for stage in STAGES:
            items = WorkItem.query.filter_by(current_stage=stage)\
                                 .order_by(WorkItem.created_at.desc())\
                                 .all()
            board[stage] = [
                {
                    "id": item.id,
                    "title": item.title,
                    "description_snippet": (item.description or "")[:80] + ("..." if item.description else ""),
                    "priority": item.priority,
                    "assignee": item.assignee,
                    # Optional: can add more flags later (overdue, regression_count, etc.)
                }
                for item in items
            ]

        return jsonify(board)


    # ────────────────────────────────────────────────
    #  6. Metrics / Analytics
    # ────────────────────────────────────────────────
    @app.route("/metrics", methods=["GET"])
    def get_metrics():
        items_per_stage = {stage: WorkItem.query.filter_by(current_stage=stage).count() for stage in STAGES}
        
        total_items = WorkItem.query.count()
        total_transitions = TransitionLog.query.count()
        
        # Calculate Average Time in Stage (Stage Aging)
        from validators import get_time_in_current_stage
        
        avg_aging_days = {}
        for stage in STAGES:
            items = WorkItem.query.filter_by(current_stage=stage).all()
            if not items:
                avg_aging_days[stage] = 0
            else:
                total_days = sum(get_time_in_current_stage(item).days for item in items)
                avg_aging_days[stage] = round(total_days / len(items), 1)

        # Basic Regressions
        regressions = db.session.query(TransitionLog.work_item_id)\
                               .filter(TransitionLog.reason.isnot(None))\
                               .group_by(TransitionLog.work_item_id)\
                               .count()
                               
        # Bottleneck detection: Where are regressions originating from?
        failure_origins = {stage: 0 for stage in STAGES}
        for log in TransitionLog.query.filter(TransitionLog.reason.isnot(None)):
            failure_origins[log.from_stage] = failure_origins.get(log.from_stage, 0) + 1

        return jsonify({
            "items_per_stage": items_per_stage,
            "total_items": total_items,
            "avg_aging_days": avg_aging_days,
            "total_stage_transitions": total_transitions,
            "items_with_regressions": regressions,
            "failure_origins": failure_origins
        })

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('ui_login'))
            return f(*args, **kwargs)
        return decorated_function

    @app.route("/ui/login", methods=["GET", "POST"])
    def ui_login():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                session['user_id'] = user.id
                session['username'] = user.username
                return redirect(url_for("ui_board"))
            return render_template("login.html", error="Invalid credentials")
        return render_template("login.html")

    @app.route("/ui/register", methods=["GET", "POST"])
    def ui_register():
        if request.method == "POST":
            username = request.form.get("username")
            password = request.form.get("password")
            role = request.form.get("role", "Developer")
            if User.query.filter_by(username=username).first():
                return render_template("register.html", error="Username already exists")
            user = User(username=username, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for("ui_board"))
        return render_template("register.html")

    @app.route("/ui/logout")
    def ui_logout():
        session.clear()
        return redirect(url_for("ui_login"))

    @app.route("/ui/projects", methods=["GET", "POST"])
    @login_required
    def ui_projects():
        if request.method == "POST":
            name = request.form.get("name")
            description = request.form.get("description")
            sdlc_practice = request.form.get("sdlc_practice", "Agile")
            if name:
                project = Project(name=name, description=description, sdlc_practice=sdlc_practice)
                db.session.add(project)
                db.session.commit()
                return redirect(url_for("ui_projects"))
        projects = Project.query.order_by(Project.created_at.desc()).all()
        return render_template("projects.html", projects=projects)

    # Optional: UI entry points (if you keep serving templates)
    @app.route("/ui/board")
    @login_required
    def ui_board():
        return render_template("board.html")

    @app.route("/ui/metrics")
    @login_required
    def ui_metrics():
        return render_template("metrics.html")
        
    @app.route("/ui/editor/<int:id>")
    @login_required
    def ui_editor(id):
        work_item = WorkItem.query.get_or_404(id)
        return render_template("editor.html", work_item=work_item)
        
    @app.route("/ui/compliance")
    @login_required
    def ui_compliance():
        items = WorkItem.query.order_by(WorkItem.id.asc()).all()
        for item in items:
            item.artifacts_list = Artifact.query.filter_by(work_item_id=item.id).order_by(Artifact.created_at).all()
            item.history_list = TransitionLog.query.filter_by(work_item_id=item.id).order_by(TransitionLog.transitioned_at).all()
        return render_template("compliance.html", items=items)