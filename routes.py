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

    def api_login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({"error": "Authentication required. Please log in."}), 401
            return f(*args, **kwargs)
        return decorated_function

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
    @api_login_required
    def create_workitem():
        data = request.get_json(silent=True) or {}
        
        if not data.get("title"):
            return jsonify({"error": "title is required"}), 400

        work_item = WorkItem(
            title=data["title"],
            description=data.get("description", ""),
            current_stage="Requirement",  # explicit default
            priority=data.get("priority", "Medium"),
            assignee=data.get("assignee", "Unassigned"),
            owner_id=session.get('user_id')
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
        branch = request.args.get("branch") or "main"
        files = (
            CodeFile.query.filter_by(work_item_id=id, branch=branch)
            .order_by(CodeFile.updated_at.desc())
            .all()
        )
        return jsonify([f.to_dict() for f in files])

    @app.route("/workitems/<int:id>/code", methods=["POST"])
    @api_login_required
    def push_code(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        
        filename = data.get("filename")
        content = data.get("content", "")
        branch = data.get("branch") or "main"

        # Permission logic: Only the owner (workspace admin/assignee) or a global Admin can push to main
        if branch.lower() == "main":
            user_id = session.get('user_id')
            current_user = User.query.get(user_id)
            user_role = session.get('role') or (current_user.role if current_user else "Developer")
            
            # Robust comparison (casting to int)
            is_owner = (work_item.owner_id is not None and int(user_id) == int(work_item.owner_id))
            is_admin = (user_role == 'Admin')
            
            # Also check if the current user is the assignee (as another definition of 'owner')
            is_assignee = (work_item.assignee == session.get('username'))
            
            # DEBUG LOGGING (visible in terminal)
            print(f"--- PUSH PERMISSION CHECK ---")
            print(f"User ID: {user_id}, Username: {session.get('username')}, Role: {user_role}")
            print(f"WorkItem Owner ID: {work_item.owner_id}, Assignee: {work_item.assignee}")
            print(f"is_owner: {is_owner}, is_admin: {is_admin}, is_assignee: {is_assignee}")
            
            if not (is_owner or is_admin or is_assignee):
                print(">>> PUSH BLOCKED: Not authorized for main branch")
                return jsonify({"error": f"Only the owner ({work_item.assignee or 'authorized user'}) or an Admin can push to main"}), 403
            print(">>> PUSH ALLOWED")

        if not filename:
            return jsonify({"error": "filename is required"}), 400

        code_file = CodeFile.query.filter_by(
            work_item_id=id,
            filename=filename,
            branch=branch
        ).first()
        if code_file:
            code_file.content = content
        else:
            code_file = CodeFile(
                work_item_id=id,
                filename=filename,
                branch=branch,
                content=content
            )
            db.session.add(code_file)
            
        db.session.commit()

        return jsonify({
            "message": "Code pushed successfully",
            "file": code_file.to_dict()
        }), 201


    @app.route("/workitems/<int:id>/branches", methods=["GET", "POST"])
    def manage_branches(id):
        """
        Lightweight branch management for the code workspace.

        - GET:  returns distinct branch names for this work item
        - POST: creates a new branch by copying files from an existing branch (default: current 'main')
        """
        work_item = WorkItem.query.get_or_404(id)

        if request.method == "GET":
            # Branches backed by files
            branch_rows = (
                db.session.query(CodeFile.branch)
                .filter_by(work_item_id=id)
                .distinct()
                .all()
            )
            file_branches = {row[0] for row in branch_rows}

            # Explicit branches with no files yet
            meta_branches = {
                b.name for b in WorkspaceBranch.query.filter_by(work_item_id=id).all()
            }

            existing = file_branches.union(meta_branches)

            # Always expose 'main' as a logical default branch
            if not existing:
                branches = ["main"]
            else:
                branches = sorted(existing)
                if "main" not in branches:
                    branches.insert(0, "main")

            return jsonify({"branches": branches})

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        from_branch = (data.get("from_branch") or "main").strip()

        if not name:
            return jsonify({"error": "name is required"}), 400

        if name == from_branch:
            return jsonify({"error": "Branch name must differ from source branch"}), 400

        if name.lower() == "main":
            return jsonify({"error": "Cannot create a branch named 'main'"}), 400

        # Prevent duplicate branch creation – either in metadata or files
        existing_meta = WorkspaceBranch.query.filter_by(
            work_item_id=id,
            name=name
        ).first()
        existing_files = (
            db.session.query(CodeFile.id)
            .filter_by(work_item_id=id, branch=name)
            .first()
        )

        if existing_meta or existing_files:
            return jsonify({"error": "Branch already exists"}), 400

        branch = WorkspaceBranch(work_item_id=id, name=name, created_by_id=session.get('user_id'))
        db.session.add(branch)
        db.session.commit()

        return jsonify({
            "message": "Branch created",
            "branch": name,
            "from_branch": from_branch,
            "file_count": 0
        }), 201


    @app.route("/workitems/<int:id>/merge", methods=["POST"])
    @api_login_required
    def merge_code(id):
        """
        Merges code from a source branch into a target branch (default: main).
        Only the workspace creator or a global Admin can perform merges.
        """
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        source_branch = (data.get("source_branch") or "").strip()
        target_branch = (data.get("target_branch") or "main").strip()

        if not source_branch:
            return jsonify({"error": "source_branch is required"}), 400
        
        if source_branch.lower() == target_branch.lower():
            return jsonify({"error": "Source and target branches must be different"}), 400

        # Check permissions: Owner, Assignee, OR Global Admin
        user_id = session.get('user_id')
        current_user = User.query.get(user_id)
        user_role = session.get('role') or (current_user.role if current_user else "Developer")

        is_owner = (work_item.owner_id is not None and int(user_id) == int(work_item.owner_id))
        is_admin = (user_role == 'Admin')
        is_assignee = (work_item.assignee == session.get('username'))

        if not (is_owner or is_admin or is_assignee):
            return jsonify({"error": "Only the workspace owner or an Admin can merge code"}), 403

        # Github logic: copy all files from source branch to target branch
        source_files = CodeFile.query.filter_by(work_item_id=id, branch=source_branch).all()
        if not source_files:
            return jsonify({"error": f"No files found in source branch '{source_branch}'"}), 404

        for s_file in source_files:
            t_file = CodeFile.query.filter_by(
                work_item_id=id, 
                filename=s_file.filename, 
                branch=target_branch
            ).first()
            
            if t_file:
                t_file.content = s_file.content
            else:
                t_file = CodeFile(
                    work_item_id=id,
                    filename=s_file.filename,
                    branch=target_branch,
                    content=s_file.content
                )
                db.session.add(t_file)
        
        # Mark as merged if target is main
        if target_branch.lower() == "main":
            source_meta = WorkspaceBranch.query.filter_by(work_item_id=id, name=source_branch).first()
            if source_meta:
                source_meta.is_merged = True

        db.session.commit()

        return jsonify({
            "message": f"Successfully merged '{source_branch}' into '{target_branch}'",
            "source": source_branch,
            "target": target_branch,
            "files_merged": len(source_files)
        })


    @app.route("/workitems/<int:id>/code/delete", methods=["POST"])
    @api_login_required
    def delete_code_file(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        filename = data.get("filename")
        branch_name = data.get("branch") or "main"

        if not filename:
            return jsonify({"error": "filename is required"}), 400

        user_id = session.get('user_id')
        current_user = User.query.get(user_id)
        user_role = session.get('role') or (current_user.role if current_user else "Developer")
        is_owner = (work_item.owner_id is not None and int(user_id) == int(work_item.owner_id))
        is_admin = (user_role == 'Admin')

        # Rule: Only owner/Admin can delete files in main
        if branch_name.lower() == "main":
            if not (is_owner or is_admin):
                return jsonify({"error": "Only the workspace owner or an Admin can delete files in the main branch"}), 403
        else:
            # For other branches, owner/Admin can always delete. 
            # Normal users can delete if they created the branch and it's not merged.
            branch_meta = WorkspaceBranch.query.filter_by(work_item_id=id, name=branch_name).first()
            is_branch_creator = (branch_meta and branch_meta.created_by_id is not None and int(user_id) == int(branch_meta.created_by_id))
            
            if not (is_owner or is_admin):
                if not is_branch_creator:
                    return jsonify({"error": "You do not have permission to delete files in this branch"}), 403
                if branch_meta.is_merged:
                    return jsonify({"error": "Cannot delete files in a branch that has already been merged by the owner"}), 403

        code_file = CodeFile.query.filter_by(
            work_item_id=id,
            filename=filename,
            branch=branch_name
        ).first()

        if not code_file:
            return jsonify({"error": "File not found"}), 404

        db.session.delete(code_file)
        db.session.commit()

        return jsonify({"message": f"File '{filename}' deleted successfully from branch '{branch_name}'"})


    @app.route("/workitems/<int:id>/branches/delete", methods=["POST"])
    @api_login_required
    def delete_branch(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}
        branch_name = data.get("name")

        if not branch_name:
            return jsonify({"error": "branch name is required"}), 400

        if branch_name.lower() == "main":
            return jsonify({"error": "The main branch cannot be deleted"}), 400

        user_id = session.get('user_id')
        current_user = User.query.get(user_id)
        user_role = session.get('role') or (current_user.role if current_user else "Developer")
        is_owner = (work_item.owner_id is not None and int(user_id) == int(work_item.owner_id))
        is_admin = (user_role == 'Admin')

        branch_meta = WorkspaceBranch.query.filter_by(work_item_id=id, name=branch_name).first()
        is_branch_creator = (branch_meta and branch_meta.created_by_id is not None and int(user_id) == int(branch_meta.created_by_id))

        # Only owner/Admin or Branch Creator (if not merged) can delete
        if not (is_owner or is_admin):
            if not is_branch_creator:
                return jsonify({"error": "Only the workspace owner or the branch creator can delete this branch"}), 403
            if branch_meta and branch_meta.is_merged:
                return jsonify({"error": "Cannot delete a branch that has already been merged by the owner"}), 403

        # Delete all files in this branch
        CodeFile.query.filter_by(work_item_id=id, branch=branch_name).delete()
        
        # Delete branch metadata
        if branch_meta:
            db.session.delete(branch_meta)
            
        db.session.commit()

        return jsonify({"message": f"Branch '{branch_name}' and its files deleted successfully"})


    # ────────────────────────────────────────────────
    #  4. Stage Transition (core enforcement point)
    # ────────────────────────────────────────────────
    @app.route("/workitems/<int:id>/transition", methods=["POST"])
    @api_login_required
    def transition_stage(id):
        work_item = WorkItem.query.get_or_404(id)
        data = request.get_json(silent=True) or {}

        target_stage     = data.get("target_stage")
        regression_reason = data.get("reason", "").strip()
        user_role        = data.get("user_role") or session.get("role")
        user_id          = session.get("user_id")

        if not target_stage:
            return jsonify({"error": "target_stage is required"}), 400

        allowed, message, extra = validate_transition(
            work_item=work_item,
            target_stage=target_stage,
            regression_reason=regression_reason if regression_reason else None,
            user_role=user_role,
            requester_id=user_id
        )

        if not allowed:
            status_code = 400
            if "FORBIDDEN" in message:
                status_code = 403
                
            return jsonify({
                "blocked": True,
                "reason": message,
                "meta": extra
            }), status_code

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