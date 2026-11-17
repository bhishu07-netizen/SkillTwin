# Deploy SkillTwin to a live link (Render, free) — from a Mac with VS Code

Result: a public URL like `https://skilltwin.onrender.com` that judges open in a browser. Nothing to install on their side.

## A. Put the project on GitHub
1. Create a free account at https://github.com, then click **New repository** → name it `skilltwin` → **Private** is fine → **Create**.
2. In VS Code open the `SkillTwin` folder, open the terminal (Ctrl + `) and run:
   ```
   git init
   git add .
   git commit -m "SkillTwin final"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/skilltwin.git
   git push -u origin main
   ```
   (GitHub asks you to log in; if it asks for a password use a **Personal Access Token** from GitHub → Settings → Developer settings, or install GitHub Desktop and push from there.)
3. `.gitignore` already keeps `.env` (your key) and the database out of the repo. Check on github.com that **no `.env` file** is visible.

## B. Deploy on Render
1. Go to https://render.com → sign up with GitHub.
2. **New +** → **Blueprint** → pick your `skilltwin` repo → **Apply**. Render reads `render.yaml` and sets everything up (about 3–5 minutes for the first build).
   - Prefer manual? **New + → Web Service** → connect repo → Runtime **Python 3** →
     Build: `pip install -r backend/requirements.txt` →
     Start: `cd backend && gunicorn app:app --workers 1 --threads 8 --timeout 90 --bind 0.0.0.0:$PORT` →
     Plan **Free** → add env var `SKILLTWIN_TRUST_PROXY` = `1`.
3. When it says **Live**, open the URL at the top of the page. Click **Continue as demo candidate**.
4. To show the SAS hackathon prototype: on a phone tap **More (three dots) → Market scorecard**; on a laptop click **Market scorecard** in the left menu.

## C. Add the Gemini key (optional)
Render dashboard → your service → **Environment** → **Add Environment Variable**:
`GEMINI_API_KEY` = your key → **Save** (it redeploys). Then open `YOUR_URL/api/ai/status` → `"configured": true`.
Never put the key in the code or in GitHub.

## D. Before the demo
- **Free tier sleeps after ~15 min idle**; the first load can take ~30–60 s. Open the link yourself 5 minutes before presenting.
- The database is **temporary** on the free tier (it resets when the service restarts/redeploys). That is fine for a demo: **Demo login → Reverse Engineer → Load judge demo profile** works from a fresh start. Take your Python/SQL assessment live, or just before the demo.
- Keep the **local version** (`./run.sh`) ready as a backup in case the venue Wi-Fi is bad.

## Update after changes
Edit → `git add . && git commit -m "update" && git push` → Render redeploys automatically.


## If Gemini shows "quota exceeded" (HTTP 429)

The app handles it: it tries the next model, skips a model that just hit its limit for 60 seconds, and reuses
identical answers for 10 minutes. Scores, fit and roadmaps never use Gemini, so they keep working. To get more
quota, create the API key in a new Google AI Studio project (quota is per project) and update `GEMINI_API_KEY`
in Render. Check with `/api/ai/status?test=1`.
