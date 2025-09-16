# main.py
import os
import logging
import requests
import time
from rapidfuzz import process, fuzz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("8295436325:AAGUFpFEUMY8wJvQw_71ABw8CogP838pFro")
HF_TOKEN = os.environ.get("")
GITHUB_USER = os.environ.get("Raiyanify")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional
HF_MODEL = os.environ.get("HF_MODEL", "facebook/bart-large-cnn")
SUMMARY_CACHE = {}
SESSION = requests.Session()
if GITHUB_TOKEN:
    SESSION.headers.update({"Authorization": f"token {GITHUB_TOKEN}"})

def list_repos():
    url = f"https://api.github.com/users/{GITHUB_USER}/repos?per_page=100"
    resp = SESSION.get(url, timeout=20)
    resp.raise_for_status()
    repos = sorted(resp.json(), key=lambda r: r.get("stargazers_count", 0), reverse=True)
    return [{"name": r["name"], "html_url": r["html_url"]} for r in repos]

def fetch_readme(repo_name):
    # Try raw URL for main and master branches, then GitHub API fallback
    for branch in ("main", "master"):
        raw_url = f"https://raw.githubusercontent.com/{GITHUB_USER}/{repo_name}/{branch}/README.md"
        r = SESSION.get(raw_url, timeout=20)
        if r.status_code == 200 and r.text.strip():
            return r.text
    # fallback to API (returns base64 by default) — request raw
    api_readme = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/readme"
    r = SESSION.get(api_readme, headers={"Accept":"application/vnd.github.v3.raw"}, timeout=20)
    if r.status_code == 200:
        return r.text
    return None

def summarize_with_hf(text):
    # Shorten input to avoid hitting model limits
    text = text.strip()
    if not text:
        return "No README content available."
    if len(text) > 3000:
        text = text[:3000]
    url = f"https://api-inference.huggingface.co/models/{HF_MODEL}"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    payload = {"inputs": text, "parameters": {"max_length": 180, "min_length": 30}}
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    try:
        j = r.json()
    except Exception:
        return "Summarizer returned non-JSON response."
    # Parse common response shapes
    if isinstance(j, dict) and j.get("error"):
        return f"Summarizer error: {j.get('error')}"
    if isinstance(j, list) and len(j) > 0:
        first = j[0]
        if isinstance(first, dict):
            return first.get("summary_text") or first.get("generated_text") or str(first)
        return str(first)
    if isinstance(j, str):
        return j
    return "Couldn't parse summarizer response."

def get_project_summary(repo_name):
    if repo_name in SUMMARY_CACHE:
        return SUMMARY_CACHE[repo_name]
    readme = fetch_readme(repo_name)
    if not readme:
        summary = "README not found for this project."
    else:
        summary = summarize_with_hf(readme)
    SUMMARY_CACHE[repo_name] = summary
    return summary

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("👋 Hi! I can summarize projects from my GitHub.\n\n"
            "Try:\n- 'Summarize retail-sales'\n- 'Tell me about sales-dashboard'\n- '/projects' to list repos")
    await update.message.reply_text(text)

async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        repos = list_repos()
        if not repos:
            await update.message.reply_text("No repos found.")
            return
        buttons = [
            [InlineKeyboardButton(r["name"], url=r["html_url"])]
            for r in repos[:12]
        ]
        await update.message.reply_text("Here are some repos:", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text("Failed to fetch repos.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return
    # quick commands
    if text.lower().startswith("list") or "project" in text.lower():
        await projects_cmd(update, context)
        return

    # Prepare repo names for matching
    try:
        repos = list_repos()
        names = [r["name"] for r in repos]
    except Exception:
        names = list(SUMMARY_CACHE.keys())

    # fuzzy match
    match = process.extractOne(text, names, scorer=fuzz.WRatio)
    if match and match[1] >= 55:  # score threshold
        repo = match[0]
        await update.message.reply_text(f"🔎 Found project: *{repo}*\nSummarizing...", parse_mode="Markdown")
        summary = get_project_summary(repo)
        await update.message.reply_text(f"*{repo}*\n\n{summary}", parse_mode="Markdown", disable_web_page_preview=True)
        return

    # fallback: user might prefix with "summarize <name>"
    words = text.split()
    if len(words) >= 2 and words[0].lower() in ("summarize", "describe", "about", "tell"):
        name = " ".join(words[1:])
        match = process.extractOne(name, names, scorer=fuzz.WRatio)
        if match and match[1] >= 50:
            repo = match[0]
            summary = get_project_summary(repo)
            await update.message.reply_text(f"*{repo}*\n\n{summary}", parse_mode="Markdown", disable_web_page_preview=True)
            return

    await update.message.reply_text("I couldn't find a clear project match. Try the repo name or /projects.")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable missing.")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("projects", projects_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    logger.info("Bot starting — running polling.")
    app.run_polling()

if __name__ == "__main__":
    main()
