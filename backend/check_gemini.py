"""Run:  python check_gemini.py   -> tells you whether your Gemini key works. Never prints the key."""
import llm
if not llm.configured():
    raise SystemExit("NOT CONFIGURED: set GEMINI_API_KEY (copy .env.example to backend/.env and paste your key).")
print("Key found. Model:", llm.model_name(), "- calling Gemini...")
out = llm.generate("Reply with exactly the single word: ready")
print("WORKING - Gemini replied:", out) if out else print("FAILED -", llm.last_error(), "\nCheck the key at https://aistudio.google.com/apikey")
