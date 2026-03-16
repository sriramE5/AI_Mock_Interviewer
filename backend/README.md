# AI Mock Interviewer Backend

## 🚀 Deployment on Render

### 📋 Prerequisites
- GitHub repository with the backend code
- Render account (free tier available)
- Gemini API keys configured in environment variables

### 🔧 Setup Instructions

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Add backend for Render deployment"
   git push origin main
   ```

2. **Create Render Service**
   - Go to [Render Dashboard](https://render.com/)
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Select the `backend` folder as root directory
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

3. **Environment Variables**
   Add these in Render Dashboard:
   ```
   GEMINI_API_KEY1=your_first_api_key
   GEMINI_API_KEY2=your_second_api_key
   PORT=10000
   ```

4. **Deploy**
   - Click "Create Web Service"
   - Wait for deployment (2-3 minutes)

### 🌐 API Endpoints

Once deployed, your API will be available at:
```
https://your-app-name.onrender.com

POST /api/interview/start
POST /api/interview/start-hr
POST /api/interview/answer
POST /api/interview/feedback
POST /api/interview/clarify
POST /api/interview/end
```

### 🔧 Frontend Configuration

Update your frontend server URL in `index.html`:
```javascript
const serverUrl = "https://your-app-name.onrender.com";
```

### 📄 Features

- ✅ HR Interview with resume upload (PDF/DOCX parsing)
- ✅ Technical and Non-technical interviews
- ✅ Voice interface support
- ✅ Real-time AI responses
- ✅ Session management
- ✅ Error handling

### 🛠️ Technologies

- FastAPI (Python web framework)
- Gemini AI (Google)
- PyPDF2 (PDF parsing)
- python-docx (DOCX parsing)
- Uvicorn (ASGI server)
