from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class WorkItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    current_stage = db.Column(db.String(50), default="Requirement")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    artifacts = db.relationship('Artifact', backref='work_item', lazy=True)
    transition_logs = db.relationship('TransitionLog', backref='work_item', lazy=True)

class Artifact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(db.Integer, db.ForeignKey('work_item.id'), nullable=False)
    stage = db.Column(db.String(50), nullable=False)
    artifact_type = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class TransitionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    work_item_id = db.Column(db.Integer, db.ForeignKey('work_item.id'), nullable=False)
    from_stage = db.Column(db.String(50), nullable=False)
    to_stage = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text)
    transitioned_at = db.Column(db.DateTime, default=datetime.utcnow)