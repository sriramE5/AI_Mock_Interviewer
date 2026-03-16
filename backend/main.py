from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from google import genai
import markdown2
try:
    from backend.prompts import INTERVIEW_PROMPT_BASE, FEEDBACK_PROMPT_BASE, CLARIFY_PROMPT_BASE, SUMMARY_PROMPT_BASE
    from backend.interview_manager import InterviewManager
except ImportError:
    from prompts import INTERVIEW_PROMPT_BASE, FEEDBACK_PROMPT_BASE, CLARIFY_PROMPT_BASE, SUMMARY_PROMPT_BASE
    from interview_manager import InterviewManager

# Load environment variables
load_dotenv()

app = FastAPI()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup Gemini Clients
api_key1 = os.getenv("GEMINI_API_KEY1")
api_key2 = os.getenv("GEMINI_API_KEY2")

# Initialize clients only if keys are present
client1 = genai.Client(api_key=api_key1) if api_key1 else None
client2 = genai.Client(api_key=api_key2) if api_key2 else None

class StartInterviewRequest(BaseModel):
    domain: str

class AnswerRequest(BaseModel):
    session_id: str
    answer: str

class FeedbackRequest(BaseModel):
    session_id: str

class ClarifyRequest(BaseModel):
    session_id: str

class EndInterviewRequest(BaseModel):
    session_id: str

async def generate_reply(prompt: str, client):
    if not client:
        raise Exception("API Key not configured")
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text

async def call_gemini(prompt: str):
    try:
        reply_text = await generate_reply(prompt, client1)
    except Exception as e1:
        print(f"Client 1 failed: {e1}")
        error_msg = str(e1)
        # Check for 503 (Service Unavailable) or 429 (Resource Exhausted)
        if client2 and ("503" in error_msg or "Service temporarily unavailable" in error_msg or "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg):
            print("Switching to Client 2...")
            try:
                reply_text = await generate_reply(prompt, client2)
            except Exception as e2:
                print(f"Client 2 failed: {e2}")
                raise HTTPException(status_code=503, detail="Service is currently busy or quota exceeded. Please try again later.")
        else:
            raise HTTPException(status_code=500, detail=f"Error: {error_msg}")
    return reply_text

@app.post("/api/interview/start")
async def start_interview(req: StartInterviewRequest):
    session = InterviewManager.create_session(req.domain)
    
    # Generate the first question
    prompt = INTERVIEW_PROMPT_BASE.format(
        domain=session.domain,
        stage=session.interview_stage,
        context="No history yet.",
        lastResponse="Starting interview"
    )
    
    question = await call_gemini(prompt)
    session.questions.append(question)
    
    return {"session_id": session.session_id, "reply": question}

@app.post("/api/interview/answer")
async def answer_question(req: AnswerRequest):
    session = InterviewManager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session.answers.append(req.answer)
    session.last_user_response = req.answer
    
    # Logic to switch stage
    if session.interview_stage == 'basic' and len(session.questions) >= 5:
        session.interview_stage = 'technical'
    
    formatted_context = session.format_context()
    
    prompt = INTERVIEW_PROMPT_BASE.format(
        domain=session.domain,
        stage=session.interview_stage,
        context=formatted_context,
        lastResponse=session.last_user_response
    )
    
    question = await call_gemini(prompt)
    session.questions.append(question)
    
    return {"reply": question}

@app.post("/api/interview/feedback")
async def get_feedback(req: FeedbackRequest):
    session = InterviewManager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if not session.last_user_response:
        return {"reply": "Please answer a question first."}

    formatted_context = session.format_context()
    
    prompt = FEEDBACK_PROMPT_BASE.format(
        domain=session.domain,
        context=formatted_context,
        lastResponse=session.last_user_response
    )
    
    feedback = await call_gemini(prompt)
    session.feedback.append(feedback)
    
    return {"reply": feedback}

@app.post("/api/interview/clarify")
async def clarify_question(req: ClarifyRequest):
    session = InterviewManager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if not session.questions:
        return {"reply": "No question to clarify."}
        
    last_question = session.questions[-1]
    formatted_context = session.format_context()
    
    prompt = CLARIFY_PROMPT_BASE.format(
        domain=session.domain,
        context=formatted_context,
        question=last_question,
        lastResponse=session.last_user_response or "No response yet"
    )
    
    clarification = await call_gemini(prompt)
    return {"reply": clarification}

@app.post("/api/interview/end")
async def end_interview(req: EndInterviewRequest):
    session = InterviewManager.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    formatted_context = session.format_context()
    
    prompt = SUMMARY_PROMPT_BASE.format(
        domain=session.domain,
        context=formatted_context
    )
    
    summary = await call_gemini(prompt)
    
    # Cleanup session? Or keep it for a bit?
    # For now, let's keep it in memory or delete it. The logic said "end_session" deletes it.
    InterviewManager.end_session(req.session_id)
    
    return {"reply": summary}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
