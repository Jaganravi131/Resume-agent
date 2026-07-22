"""Quick smoke test for the resume_evaluator module."""
import sys, os, importlib.util
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["RESUME_NAME"] = "Jagan Babu R"
os.environ.setdefault("GOOGLE_API_KEY", "")

# Import resume_evaluator directly to bypass __init__.py -> agent.py -> google.adk
_spec = importlib.util.spec_from_file_location(
    "resume_evaluator",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_evaluator.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sanitize_resume_text = _mod.sanitize_resume_text
evaluate_resume_quality = _mod.evaluate_resume_quality

dirty = (
    "Jagan Babu R\n"
    "Email: jaganravi131@gmail.com | Phone: +91-8124819503\n"
    "LinkedIn: https://www.linkedin.com/in/jagan-babu-r/\n"
    "\n"
    "PROFESSIONAL SUMMARY\n"
    "Detail-oriented software engineer.\n"
    "\n"
    "CORE SKILLS\n"
    "- Python, Flask, FastAPI\n"
    "- Docker, AWS\n"
    "\n"
    "EXPERIENCE\n"
    "- Built REST APIs serving 10000+ requests/day\n"
    "- Improved test coverage by 40%\n"
    "\n"
    "PROJECTS\n"
    "- Career Copilot: Built an agentic pipeline\n"
    "\n"
    "EDUCATION\n"
    "- B.Tech Computer Science\n"
    "\n"
    "C:\\PROJECT_FILE\\AI_ML_projects\\adk-workspace\\resume.pdf\n"
    "[Tool] Searching job postings for query\n"
    'Keywords: python, flask, docker, aws\n'
    '"resume_pdf": "C:\\some\\path.pdf"\n'
    "```python\n"
    "some code fence\n"
    "```\n"
)

print("=== DIRTY RESUME (last 5 lines) ===")
for line in dirty.strip().splitlines()[-5:]:
    print(f"  {line}")

cleaned = sanitize_resume_text(dirty)
print("\n=== CLEANED RESUME ===")
print(cleaned)

# Verify paths are gone
assert "C:\\" not in cleaned, "File path still present!"
assert "[Tool]" not in cleaned, "[Tool] debug line still present!"
assert '```' not in cleaned, "Markdown fence still present!"
assert '"resume_pdf"' not in cleaned, "Metadata still present!"
assert "Keywords:" not in cleaned, "Keyword dump still present!"
print("\n[PASS] All path/metadata artifacts removed.")

# Test evaluate
result = evaluate_resume_quality(cleaned, "Jagan Babu R")
print(f"\nScore: {result['score']}/100")
print(f"Passed: {result['passed']}")
print(f"Issues: {result['issues']}")
print(f"Breakdown: {result['breakdown']}")

assert result["score"] > 0, "Score should be > 0"
assert result["breakdown"]["cleanliness"] == 25, "Cleaned resume should have full cleanliness score"
print("\n[PASS] All evaluator tests passed!")
