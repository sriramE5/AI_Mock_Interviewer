from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from google import genai
import markdown2
try:
    import PyPDF2
    import docx
    PDF_AVAILABLE = True
    DOCX_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    DOCX_AVAILABLE = False
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

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF file content"""
    if not PDF_AVAILABLE:
        return "PDF parsing library not available. Please install PyPDF2: pip install PyPDF2"
    
    try:
        import io
        pdf_file = io.BytesIO(pdf_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        
        text = ""
        for page_num in range(min(len(pdf_reader.pages), 10)):  # Limit to first 10 pages
            page = pdf_reader.pages[page_num]
            text += page.extract_text() + "\n"
        
        return text.strip() if text.strip() else "No text could be extracted from PDF"
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"

def extract_text_from_docx(docx_content: bytes) -> str:
    """Extract text from DOCX file content"""
    if not DOCX_AVAILABLE:
        return "DOCX parsing library not available. Please install python-docx: pip install python-docx"
    
    try:
        import io
        docx_file = io.BytesIO(docx_content)
        doc = docx.Document(docx_file)
        
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        
        return text.strip() if text.strip() else "No text could be extracted from DOCX"
    except Exception as e:
        return f"Error extracting text from DOCX: {str(e)}"

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

@app.post("/api/interview/start-with-resume")
async def start_interview_with_resume(domain: str = Form(...), resume: UploadFile = File(...)):
    # Create interview session
    session = InterviewManager.create_session(domain)
    
    # Read and process resume content
    try:
        resume_content = await resume.read()
        resume_filename = resume.filename
        content_type = resume.content_type
        
        # Extract text based on file type
        if content_type == 'application/pdf':
            resume_text = extract_text_from_pdf(resume_content)
        elif content_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']:
            resume_text = extract_text_from_docx(resume_content)
        else:
            # Try to decode as text for other formats
            try:
                resume_text = resume_content.decode('utf-8', errors='ignore')
                if len(resume_text.strip()) < 100:
                    resume_text = f"Resume file: {resume_filename}\nFile type: {content_type}\nThis appears to be a resume document, but text extraction was limited."
            except:
                resume_text = f"Resume file: {resume_filename}\nFile type: {content_type}\nThis appears to be a resume document with work experience, education, and skills."
        
        # Limit text length to avoid token limits
        if len(resume_text) > 3000:
            resume_text = resume_text[:3000] + "\n...(content truncated for processing)"
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading resume: {str(e)}")
    
    # Generate domain-specific first question based on resume
    resume_prompt = f"""You are conducting a {domain} interview. The candidate has uploaded their resume with the following content:

Resume Content:
{resume_text}

Based on this resume and the {domain} domain, ask a relevant question that would help you understand:
1. The candidate's relevant experience and skills for this domain
2. Their technical knowledge or expertise in {domain}
3. Their problem-solving abilities and approach
4. Their career goals and motivations related to {domain}

Important guidelines:
- Ask a natural, conversational question relevant to {domain}
- Don't explicitly mention "I saw on your resume"
- Make it sound like you're genuinely interested in their background
- Focus on their experience, skills, or aspirations relevant to {domain}
- Keep it professional and engaging
- Ask only one question at a time

Ask your first question:"""

    try:
        question = await call_gemini(resume_prompt)
        
        # Store resume context in the session for future questions
        session.resume_context = resume_text
        
        return {"session_id": session.session_id, "reply": question}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating question: {str(e)}")

@app.post("/api/audio/analyze")
async def analyze_audio(audio_data: dict):
    try:
        audio_base64 = audio_data.get("audio")
        interview_context = audio_data.get("interview_context", {})
        
        if not audio_base64:
            raise HTTPException(status_code=400, detail="No audio data provided")
        
        # Decode base64 audio
        import base64
        audio_bytes = base64.b64decode(audio_base64)
        
        # Create a temporary file for the audio
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_file:
            temp_file.write(audio_bytes)
            temp_file_path = temp_file.name
        
        try:
            # Analyze audio with Gemini
            analysis_prompt = f"""Analyze this audio recording of an interview response and provide detailed feedback on the following aspects:

1. **Speaking Pace**: Rate as Slow, Normal, or Fast
2. **Confidence Level**: Rate as Low, Medium, or High  
3. **Emotion Detected**: Identify the primary emotion (Confident, Nervous, Enthusiastic, Neutral, etc.)
4. **Clarity Score**: Rate from 1-10 for speech clarity
5. **Filler Words**: Count and list common filler words used (um, uh, like, you know, etc.)

Interview Context:
- Domain: {interview_context.get('domain', 'Unknown')}
- Session ID: {interview_context.get('sessionId', 'Unknown')}

Provide your analysis in JSON format with the following structure:
{{
    "speaking_pace": "Normal",
    "confidence_level": "Medium", 
    "emotion_detected": "Confident",
    "clarity_score": "8/10",
    "filler_words": "um: 3, uh: 2, like: 1"
}}

Focus on providing constructive feedback that would help the candidate improve their interview performance."""

            # For now, return a mock analysis since we don't have Gemini audio processing set up
            # In a real implementation, you would send the audio to Gemini for analysis
            mock_analysis = {
                "speaking_pace": "Normal",
                "confidence_level": "Medium",
                "emotion_detected": "Confident", 
                "clarity_score": "7/10",
                "filler_words": "um: 2, uh: 1"
            }
            
            return mock_analysis
            
        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing audio: {str(e)}")

@app.post("/api/interview/start-hr")
async def start_hr_interview(resume: UploadFile = File(...)):
    # Create HR interview session
    session = InterviewManager.create_session("hr-interview")
    
    # Read and process resume content
    try:
        resume_content = await resume.read()
        resume_filename = resume.filename
        content_type = resume.content_type
        
        # Extract text based on file type
        if content_type == 'application/pdf':
            resume_text = extract_text_from_pdf(resume_content)
        elif content_type in ['application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/msword']:
            resume_text = extract_text_from_docx(resume_content)
        else:
            # Try to decode as text for other formats
            try:
                resume_text = resume_content.decode('utf-8', errors='ignore')
                if len(resume_text.strip()) < 100:
                    resume_text = f"Resume file: {resume_filename}\nFile type: {content_type}\nThis appears to be a resume document, but text extraction was limited."
            except:
                resume_text = f"Resume file: {resume_filename}\nFile type: {content_type}\nThis appears to be a resume document with work experience, education, and skills."
        
        # Limit text length to avoid token limits
        if len(resume_text) > 3000:
            resume_text = resume_text[:3000] + "\n...(content truncated for processing)"
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading resume: {str(e)}")
    
    # Generate HR-specific first question based on resume
    hr_prompt = f"""You are conducting an HR interview. The candidate has uploaded their resume with the following content:

Resume Content:
{resume_text}

Based on this resume, ask a relevant HR question that would help you understand:
1. The candidate's work experience and achievements
2. Their skills and qualifications 
3. Their career goals and motivations
4. Their fit for potential roles

Important guidelines:
- Ask a natural, conversational question
- Don't explicitly mention "I saw on your resume"
- Make it sound like you're genuinely interested in their background
- Focus on their experience, skills, or career aspirations
- Keep it professional and engaging

Example questions:
- "Tell me about your most significant professional achievement."
- "What motivated you to pursue this career path?"
- "How would you describe your leadership style?"
- "What skills do you feel are your strongest assets?"
"""
    
    question = await call_gemini(hr_prompt)
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
    
    # For HR interviews, continue with resume-based questions
    if session.domain == 'hr-interview':
        hr_prompt = f"""You are conducting an HR interview. The candidate has been answering questions about their background.

Previous Questions and Answers:
{formatted_context}

Candidate's latest response: {req.answer}

Based on their response and the conversation so far, ask a follow-up HR question that:
1. Digs deeper into their experience or skills
2. Explores their motivations and career goals
3. Assesses their fit for the role
4. Evaluates their soft skills or leadership qualities

Important guidelines:
- Make it conversational and natural
- Build upon their previous answers
- Don't repeat questions already asked
- Focus on behavioral or situational questions
- Keep it professional and engaging

Example follow-up questions:
- "Can you give me a specific example of when you demonstrated that skill?"
- "How did you handle a challenging situation with a team member?"
- "What attracts you to this type of role?"
- "Where do you see yourself in 5 years?"
"""
        question = await call_gemini(hr_prompt)
    else:
        # Regular interview flow for other domains
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
    import os
    
    # Check if running on Render
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if os.environ.get("RENDER") else "127.0.0.1"
    
    uvicorn.run(app, host=host, port=port)
