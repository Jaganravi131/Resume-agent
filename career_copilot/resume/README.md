# Base Resumes (local only — never committed)

Place your resume PDF(s) here:

```
career_copilot/resume/
├── Resume_latest.pdf    ← your most recent resume (canonical source)
└── Resume (1).pdf       ← optional older versions (ignored when latest exists)
```

**Why gitignored?** These files contain personal PII (name, phone, email,
address). `*.pdf` in this directory is excluded from git; the tailoring engine
reads them locally as source material. If an old commit still contains resume
PDFs, purge history with `git filter-repo` before publishing the repository.
