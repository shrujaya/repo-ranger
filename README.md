```
reporanger/
├── .github/
│   └── workflows/          # CI/CD for RepoRanger itself (testing, linting)
├── apps/
│   └── dispatcher/         # The FastAPI server (runs on Vercel)
│       ├── main.py         # Entry point & Webhook routes
│       ├── github_api.py   # Auth & logic to trigger GitHub Actions
│       ├── requirements.txt
│       └── vercel.json     # Vercel deployment config
├── worker/                 # The logic that runs in the USER'S repo
│   ├── action.yml          # GitHub Action metadata (the "bridge")
│   ├── main.py             # Script entry point (routes to Review or Cleanup)
│   ├── reviewer.py         # SLM logic for PR analysis
│   ├── janitor.py          # Dead branch identification logic
│   ├── prompts.py          # The "Senior Engineer" SLM prompt templates
│   └── requirements.txt
├── templates/
│   └── ai-bot.yml          # The workflow file you "gift" to users
├── README.md               # The "Storefront" and installation guide
├── CONTRIBUTING.md         # The "Rules of the Road" for collaborators
└── LICENSE                 # Legal framework (e.g., Apache 2.0)
```
