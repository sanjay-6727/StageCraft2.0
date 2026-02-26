from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, UniqueConstraint, func
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import uuid

db = SQLAlchemy()


def short_uuid():
    """Short unique identifier – useful for external references or short URLs."""
    return str(uuid.uuid4())[:10]


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(50), nullable=False, default="Developer") # Developer, Tester, Architect, Manager, Admin

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "role": self.role}


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    sdlc_practice = db.Column(db.String(50), nullable=False, default="Agile")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    work_items = db.relationship(
        'WorkItem',
        back_populates='project',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='select'
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class WorkItem(db.Model):
    __tablename__ = 'work_items'

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(12), unique=True, nullable=False, default=short_uuid, index=True)

    project_id = db.Column(
        db.Integer,
        db.ForeignKey('projects.id', ondelete='CASCADE'),
        nullable=False,
        default=1,
        index=True
    )

    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)

    current_stage = db.Column(db.String(50), nullable=False, default="Requirement", index=True)

    # Governance & analytics fields
    regression_count = db.Column(db.Integer, nullable=False, default=0)
    transition_count  = db.Column(db.Integer, nullable=False, default=0)
    
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    assignee = db.Column(db.String(100), nullable=True, default="Unassigned")

    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at  = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=func.current_timestamp()
    )
    last_transition_at = db.Column(db.DateTime, nullable=True)

    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    project = db.relationship('Project', back_populates='work_items')
    owner = db.relationship('User', foreign_keys=[owner_id])

    artifacts = db.relationship(
        'Artifact',
        back_populates='work_item',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='select'
    )

    transition_logs = db.relationship(
        'TransitionLog',
        back_populates='work_item',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='select',
        order_by='TransitionLog.transitioned_at.asc()'
    )

    comments = db.relationship(
        'Comment',
        back_populates='work_item',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='select',
        order_by='Comment.created_at.asc()'
    )

    code_files = db.relationship(
        'CodeFile',
        back_populates='work_item',
        cascade='all, delete-orphan',
        passive_deletes=True,
        lazy='select',
        order_by='CodeFile.updated_at.desc()'
    )

    __table_args__ = (
        Index('ix_workitem_stage_created', 'current_stage', 'created_at'),
    )

    def __repr__(self):
        return f"<WorkItem #{self.id} '{self.title[:35]}…' stage={self.current_stage}>"

    def to_dict(self, detailed=False):
        base = {
            "id": self.id,
            "public_id": self.public_id,
            "project_id": self.project_id,
            "title": self.title,
            "current_stage": self.current_stage,
            "priority": self.priority,
            "assignee": self.assignee,
            "regression_count": self.regression_count,
            "transition_count": self.transition_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if detailed:
            base.update({
                "description": self.description,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "last_transition_at": (
                    self.last_transition_at.isoformat() if self.last_transition_at else None
                ),
            })
        return base


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    author = db.Column(db.String(100), nullable=False, default="User")
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    work_item = db.relationship('WorkItem', back_populates='comments')

    def to_dict(self):
        return {
            "id": self.id,
            "author": self.author,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class CodeFile(db.Model):
    __tablename__ = 'code_files'

    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    filename = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(100), nullable=False, default="main")
    content = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_item = db.relationship('WorkItem', back_populates='code_files')

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "branch": self.branch,
            "content": self.content,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class WorkspaceBranch(db.Model):
    """
    Explicit branch metadata per work item so that branches can exist
    even before any files are pushed.
    """

    __tablename__ = 'workspace_branches'

    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_merged = db.Column(db.Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint('work_item_id', 'name', name='uq_workspace_branch_per_item'),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "work_item_id": self.work_item_id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Artifact(db.Model):
    __tablename__ = 'artifacts'

    id = db.Column(db.Integer, primary_key=True)

    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    stage = db.Column(db.String(50), nullable=False, index=True)
    artifact_type = db.Column(db.String(120), nullable=False)

    # Where the real content is stored (commit hash, URL, file path, external doc ID, …)
    reference = db.Column(db.String(500), nullable=True)
    
    # NEW: File metadata for artifact versioning / upload
    file_blob = db.Column(db.LargeBinary, nullable=True) # Could store real file content
    version = db.Column(db.Integer, nullable=False, default=1)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)

    # Human-readable note / justification
    comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationship
    work_item = db.relationship('WorkItem', back_populates='artifacts')

    __table_args__ = (
        Index('ix_artifact_stage_type', 'stage', 'artifact_type'),
    )

    def __repr__(self):
        ref = f" ref={self.reference[:20]}…" if self.reference else ""
        return f"<Artifact {self.artifact_type}{ref} @ {self.stage} WI#{self.work_item_id} v{self.version}>"

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.artifact_type,
            "stage": self.stage,
            "reference": self.reference,
            "comment": self.comment,
            "version": self.version,
            "is_locked": self.is_locked,
            "has_file": self.file_blob is not None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Approval(db.Model):
    __tablename__ = 'approvals'

    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    stage = db.Column(db.String(50), nullable=False)
    required_role = db.Column(db.String(50), nullable=False)
    
    # ID of the user who signed off
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="Pending") # Pending, Approved, Rejected
    
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Signature / trace
    digital_signature = db.Column(db.String(64), nullable=True)

    work_item = db.relationship('WorkItem', backref=db.backref('approvals', cascade='all, delete-orphan'))
    # Optional: approver relationship
    
    def to_dict(self):
        return {
            "id": self.id,
            "stage": self.stage,
            "required_role": self.required_role,
            "status": self.status,
            "digital_signature": self.digital_signature,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class TransitionLog(db.Model):
    __tablename__ = 'transition_logs'

    id = db.Column(db.Integer, primary_key=True)

    work_item_id = db.Column(
        db.Integer,
        db.ForeignKey('work_items.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )

    from_stage = db.Column(db.String(50), nullable=False)
    to_stage = db.Column(db.String(50), nullable=False)

    # Filled only on regressions (backward moves)
    reason = db.Column(db.Text, nullable=True)

    transitioned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Future: audit trail enhancement
    # performed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationship
    work_item = db.relationship('WorkItem', back_populates='transition_logs')

    __table_args__ = (
        Index('ix_transition_workitem_time', 'work_item_id', 'transitioned_at'),
    )

    def __repr__(self):
        direction = "→" if self.to_stage_index() > self.from_stage_index() else "←"
        return f"<Transition WI#{self.work_item_id} {self.from_stage} {direction} {self.to_stage}>"

    def to_dict(self):
        return {
            "from": self.from_stage,
            "to": self.to_stage,
            "reason": self.reason,
            "timestamp": self.transitioned_at.isoformat() if self.transitioned_at else None
        }

    def from_stage_index(self):
        from validators import STAGES  # late import to avoid circular import
        return STAGES.index(self.from_stage) if self.from_stage in STAGES else -1

    def to_stage_index(self):
        from validators import STAGES
        return STAGES.index(self.to_stage) if self.to_stage in STAGES else -1