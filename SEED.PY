from app import create_app
from models import db, WorkItem, Artifact, TransitionLog
from validators import STAGES, REQUIRED_ARTIFACTS
app = create_app()

def seed():
    with app.app_context():
        # Clear old data (optional for demo reset)
        db.drop_all() 
        db.create_all()
        
        from models import Project, User, Approval, CodeFile, Comment
        
        # Create some users
        admin = User(username="admin", role="Admin")
        admin.set_password("pass")
        user1 = User(username="alice", role="Developer")
        user1.set_password("pass")
        user2 = User(username="bob", role="Developer")
        user2.set_password("pass")
        db.session.add_all([admin, user1, user2])
        db.session.commit()

        # Seed a default project so project_id=1 doesn't fail
        db.session.add(Project(name="Global Stagecraft Init", description="Internal enterprise rollout"))
        db.session.commit()

        # ─────────────────────────────────────────
        # 1️⃣ Requirement Stage Items
        # ─────────────────────────────────────────
        w1 = WorkItem(title="User Authentication System",
                      description="Implement login, logout, and JWT-based auth.",
                      priority="Critical", assignee="Alice Hacker",
                      owner_id=user1.id)
        w2 = WorkItem(title="Payment Gateway Integration",
                      description="Integrate Stripe API for transactions.",
                      priority="High", assignee="Bob Security",
                      owner_id=user2.id)

        db.session.add_all([w1, w2])
        db.session.commit()

        # ─────────────────────────────────────────
        # 2️⃣ Design Stage Item
        # ─────────────────────────────────────────
        w3 = WorkItem(title="Dashboard Redesign",
                      description="Modernize UI with responsive layout.",
                      priority="Medium", assignee="Charlie Design")
        db.session.add(w3)
        db.session.commit()

        # Add required Requirement artifacts
        for artifact_type in REQUIRED_ARTIFACTS["Requirement"]:
            db.session.add(Artifact(
                work_item_id=w3.id,
                stage="Requirement",
                artifact_type=artifact_type
            ))

        db.session.commit()

        # Move to Design
        db.session.add(TransitionLog(
            work_item_id=w3.id,
            from_stage="Requirement",
            to_stage="Design",
            reason=None
        ))
        w3.current_stage = "Design"
        db.session.commit()

        # ─────────────────────────────────────────
        # 3️⃣ Implementation Stage Item
        # ─────────────────────────────────────────
        w4 = WorkItem(title="Email Notification Service",
                      description="Send transactional emails via SMTP.",
                      priority="Low", assignee="Dana Ops")
        db.session.add(w4)
        db.session.commit()

        # Complete Requirement + Design
        for stage in ["Requirement", "Design"]:
            for artifact_type in REQUIRED_ARTIFACTS[stage]:
                db.session.add(Artifact(
                    work_item_id=w4.id,
                    stage=stage,
                    artifact_type=artifact_type
                ))
            db.session.add(TransitionLog(
                work_item_id=w4.id,
                from_stage=stage,
                to_stage=STAGES[STAGES.index(stage)+1],
                reason=None
            ))
            w4.current_stage = STAGES[STAGES.index(stage)+1]

        db.session.commit()

        # ─────────────────────────────────────────
        # 4️⃣ Testing Stage With Regression
        # ─────────────────────────────────────────
        w5 = WorkItem(title="Report Generation Module",
                      description="Generate downloadable analytics reports.",
                      priority="High", assignee="Eve Analyst")
        db.session.add(w5)
        db.session.commit()

        # Complete Requirement → Design → Implementation
        for stage in ["Requirement", "Design", "Implementation"]:
            for artifact_type in REQUIRED_ARTIFACTS[stage]:
                db.session.add(Artifact(
                    work_item_id=w5.id,
                    stage=stage,
                    artifact_type=artifact_type
                ))
            db.session.add(TransitionLog(
                work_item_id=w5.id,
                from_stage=stage,
                to_stage=STAGES[STAGES.index(stage)+1],
                reason=None
            ))
            w5.current_stage = STAGES[STAGES.index(stage)+1]

        db.session.commit()

        from models import Comment
        db.session.add(Comment(work_item_id=w5.id, author="Test QA", content="Found performance bottlenecks."))

        # Simulate regression
        db.session.add(TransitionLog(
            work_item_id=w5.id,
            from_stage="Testing",
            to_stage="Implementation",
            reason="Critical performance issue found during load testing."
        ))
        w5.current_stage = "Implementation"

        db.session.commit()

        # ─────────────────────────────────────────
        # 5️⃣ Fully Completed Lifecycle
        # ─────────────────────────────────────────
        w6 = WorkItem(title="Role-Based Access Control",
                      description="Restrict system access based on user roles.")
        db.session.add(w6)
        db.session.commit()

        for stage in STAGES[:-1]:
            for artifact_type in REQUIRED_ARTIFACTS[stage]:
                db.session.add(Artifact(
                    work_item_id=w6.id,
                    stage=stage,
                    artifact_type=artifact_type
                ))
            db.session.add(TransitionLog(
                work_item_id=w6.id,
                from_stage=stage,
                to_stage=STAGES[STAGES.index(stage)+1],
                reason=None
            ))
            w6.current_stage = STAGES[STAGES.index(stage)+1]

        db.session.commit()

        print("✅ Test data seeded successfully.")

if __name__ == "__main__":
    seed()
