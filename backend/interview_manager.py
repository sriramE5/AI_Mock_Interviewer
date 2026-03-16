import uuid
from typing import Dict, List, Optional
from pydantic import BaseModel

# In-memory session store
sessions: Dict[str, "InterviewSession"] = {}

class InterviewSession:
    def __init__(self, domain: str):
        self.session_id = str(uuid.uuid4())
        self.domain = domain
        self.questions: List[str] = []
        self.answers: List[str] = []
        self.feedback: List[str] = []
        self.current_question_index = 0
        self.interview_stage = 'basic'
        self.last_user_response = ''

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "domain": self.domain,
            "questions": self.questions,
            "answers": self.answers,
            "feedback": self.feedback,
            "current_question_index": self.current_question_index,
            "interview_stage": self.interview_stage,
            "last_user_response": self.last_user_response,
        }

    def format_context(self) -> str:
        formatted = []
        if self.domain:
            formatted.append(f"Interview Domain: {self.domain}")
        
        formatted.append(f"Interview Stage: {self.interview_stage}")
        formatted.append("\nInterview History:")

        # Pair questions with answers
        limit = min(len(self.questions), len(self.answers))
        for i in range(limit):
            formatted.append(f"Question {i + 1}: {self.questions[i]}")
            formatted.append(f"Answer {i + 1}: {self.answers[i]}")

        # Add any unpaired questions
        if len(self.questions) > len(self.answers):
            formatted.append(f"Question {len(self.questions)}: {self.questions[-1]}")
            formatted.append("(Awaiting answer)")

        if self.feedback:
            formatted.append("\nFeedback History:")
            for i, fb in enumerate(self.feedback):
                formatted.append(f"Feedback {i + 1}: {fb}")

        return "\n".join(formatted)

class InterviewManager:
    @staticmethod
    def create_session(domain: str) -> InterviewSession:
        session = InterviewSession(domain)
        sessions[session.session_id] = session
        return session

    @staticmethod
    def get_session(session_id: str) -> Optional[InterviewSession]:
        return sessions.get(session_id)

    @staticmethod
    def end_session(session_id: str):
        if session_id in sessions:
            del sessions[session_id]
