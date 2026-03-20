import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///scorecards.db')

# SQLAlchemy strictly expects postgresql:// but some providers emit postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connect args specific for sqlite to avoid multithreading errors
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Scorecard(Base):
    __tablename__ = "scorecards"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    student_name = Column(String, nullable=False)
    registration_no = Column(String)
    qr_data = Column(String, index=True)
    image_hash = Column(String, index=True)
    gate_score = Column(String)
    branch = Column(String)
    rank = Column(Integer)
    original_filename = Column(String)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    """Initialize the database creating the table schemas."""
    Base.metadata.create_all(bind=engine)


def add_scorecard(student_name, registration_no, qr_data, image_hash, gate_score, branch, rank, original_filename):
    """Add a new scorecard entry to the database."""
    session = SessionLocal()
    try:
        new_card = Scorecard(
            student_name=student_name,
            registration_no=registration_no,
            qr_data=qr_data,
            image_hash=image_hash,
            gate_score=gate_score,
            branch=branch,
            rank=rank,
            original_filename=original_filename
        )
        session.add(new_card)
        session.commit()
        session.refresh(new_card)
        return new_card.id
    finally:
        session.close()


def check_duplicate(qr_data, image_hash):
    """
    Check if a scorecard already exists in the database.
    Matches by QR data OR image hash (perceptual hash).
    """
    session = SessionLocal()
    try:
        duplicate = None
        if qr_data:
            duplicate = session.query(Scorecard).filter(Scorecard.qr_data == qr_data).first()
                
        if not duplicate and image_hash:
            duplicate = session.query(Scorecard).filter(Scorecard.image_hash == image_hash).first()
            
        if duplicate:
            return {
                "id": duplicate.id,
                "student_name": duplicate.student_name,
                "registration_no": duplicate.registration_no,
                "qr_data": duplicate.qr_data,
                "image_hash": duplicate.image_hash,
                "gate_score": duplicate.gate_score,
                "branch": duplicate.branch,
                "rank": duplicate.rank,
                "original_filename": duplicate.original_filename,
                "uploaded_at": duplicate.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if duplicate.uploaded_at else None
            }
                
        return None
    finally:
        session.close()


def get_all_scorecards():
    """Get all scorecard entries."""
    session = SessionLocal()
    try:
        cards = session.query(Scorecard).order_by(Scorecard.uploaded_at.desc()).all()
        # Return list of dicts to match the legacy API format
        return [
            {
                "id": c.id,
                "student_name": c.student_name,
                "registration_no": c.registration_no,
                "qr_data": c.qr_data,
                "image_hash": c.image_hash,
                "gate_score": c.gate_score,
                "branch": c.branch,
                "rank": c.rank,
                "original_filename": c.original_filename,
                "uploaded_at": c.uploaded_at.strftime('%Y-%m-%d %H:%M:%S') if c.uploaded_at else None
            }
            for c in cards
        ]
    finally:
        session.close()


def delete_scorecard(record_id):
    """Delete a scorecard entry by ID."""
    session = SessionLocal()
    try:
        card = session.query(Scorecard).filter(Scorecard.id == record_id).first()
        if card:
            session.delete(card)
            session.commit()
    finally:
        session.close()


def get_scorecard_count():
    """Get total number of verified scorecards."""
    session = SessionLocal()
    try:
        return session.query(Scorecard).count()
    finally:
        session.close()
