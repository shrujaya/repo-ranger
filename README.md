<div align="center">
  <img src="logo.png" alt="RepoRanger Logo" width="200" />

  <h1 style="color: #2e8b57; margin-bottom: 0;">RepoRanger</h1>
  
  <p style="font-style: italic; color: #555555; margin-top: 5px;">The Zero-Cost, Privacy-First Repository Guardian</p>

  <p>
    <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License: MIT">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat" alt="PRs Welcome">
  </p>
</div>

RepoRanger is a powerful "Dispatcher-Worker" GitHub App that provides **AI-powered code reviews** and **automated branch hygiene**.

Unlike other SaaS solutions, RepoRanger runs entirely on your infrastructure (GitHub Actions) using a relay model. This guarantees that your code, IP, and secrets **never leave your environment**.

## ✨ Why RepoRanger?

- **🌱 Zero Infrastructure Costs**: Designed to run 100% on the Vercel Free Tier and GitHub Actions.
- **🔒 Privacy First**: Your `GROQ_API_KEY` stays safely in your GitHub Secrets.
- **⚡ Senior-Level Feedback**: Powered by Groq (Llama-3.3-70b) for lightning fast, ultra-low latency code reviews.
- **🧹 Automated Janitor**: Keep your repository spotless with rich branch hygiene reports and signed deletion links.
- **🛡️ Distributed Security**: The Dispatcher only routes webhooks; the Worker inside your repo does all the heavy lifting.

## 🛠️ Architecture

### AI Pull Request Reviewer
```mermaid
graph TD
    A[GitHub PR Event] -->|Webhook| B(Dispatcher API)
    B --> C{Event Action}
    C -- opened / synchronize --> D[Trigger GitHub Action]
    D --> E[Worker runs inside Repo]
    E -->|Analyze Diff| F[Groq AI 70B]
    F --> G[Post Review Comments to PR]
```

### Automated Branch Janitor
```mermaid
graph TD
    A[GitHub Issue Event] -->|Webhook| B(Dispatcher API)
    B --> C{Keyword Parser}
    
    C -- e.g. dead+branches=30 --> D[Trigger GitHub Action]
    D --> E[Worker runs inside Repo]
    E -->|Analyze git history| F{Stale Branches?}
    F -- Found --> G[Post Hygiene Report to Issue]
    F -- Clean --> H[Post All Clear Message]
    
    C -- Admin comments branch name --> I[Dispatcher calls GitHub API]
    I -->|Direct API Call| J[Delete Branch]
```

## 📦 Setup Instructions

### 1. Deploy the API to Vercel
Deploy the entire repository to Vercel. Vercel will automatically detect the Python app because of the `vercel.json` config mapping routes to `/api/index.py`.
You must set the following **Environment Variables** in your Vercel project settings:
- `APP_ID`: Your GitHub App ID.
- `GITHUB_APP_PRIVATE_KEY`: Your GitHub App private key (paste the entire contents of the `.pem` file).
- `WEBHOOK_SECRET`: Your GitHub App webhook secret.
- `DELETE_SECRET`: A custom string for branch deletion link signatures (e.g., `my-super-secret`).

### 2. Configure GitHub App
- **Permissions**: Pull Requests (R/W), Contents (R/W), Actions (R/W), Issues (R/W).
- **Webhooks**: Point to `https://your-vercel-app.com/webhook`.

### 3. Usage
Once installed, RepoRanger will automatically open a **Welcome PR** with instructions to add your `GROQ_API_KEY` to your secrets.

---

## 🧹 Dead Branch Janitor — Command Reference

All commands are activated by including a keyword in the **title or body of a GitHub Issue**. After the initial report, admins can reply in the **issue comments** to take action.

> **Note:** `<N>` is always a number of days. Branch names can contain letters, numbers, `/`, `.`, `_`, and `-`.

---

### 📋 Reporting Commands

Open a new Issue containing any of these keywords to trigger a report.

| Keyword | What it does |
|---------|--------------|
| `dead+branches=<N>` | One-off scan — posts a list of all branches inactive for more than `N` days. Includes a detailed table with last author, exact age, and last commit date. |
| `unmerged+only=<N>` | Reports only stale branches that have **not** been merged into the default branch (safe to review before deleting). |
| `author+report=<N>` | Groups stale branches **by last committer** — great for pinging team members to clean up their own branches. |
| `check+merged` | Reports branches that were already **fully merged** into the default branch but were never deleted ("ghost branches"). |
| `stale+pr=<N>` | Reports open PRs with no activity for more than `N` days. |
| `--help` | Lists all available commands and their descriptions in a comment. |

---

### ⏰ Scheduled Scanning

| Keyword | What it does |
|---------|--------------|
| `check+dead=<N>` | Sets up a **recurring scan** every `N` days. RepoRanger will post a fresh dead-branch report to this issue on each scheduled run. |

Once set up, you can control the schedule in **two ways**:

**Option A:** Open a **new Issue** with the command as the title — it will find and act on all open `check+dead` tracking issues.

**Option B:** Reply with the command as a **comment** on the specific tracking issue.

| Command | What it does |
|---------|--------------|
| `pause+janitor` | ⏸ Pauses all future scheduled reports. Adds a `janitor-paused` label. |
| `resume+janitor` | ▶ Resumes scheduled reports. Removes the `janitor-paused` label. |
| `stop+janitor` | 🛑 Permanently stops scanning and **closes** the tracking issue(s). |

---

### 🔒 Branch Protection

| Keyword | What it does |
|---------|--------------|
| `protect+branch=<branch-name>` | Marks a branch as protected — the janitor will **never flag or delete** it. Adds a `protected:<branch-name>` label to persist this across runs. To unprotect, manually remove the label. |

---

### 🗑️ Deletion Commands

| Trigger | Who | What it does |
|---------|-----|--------------|
| Reply with exact `branch-name` in a comment | Owner / Member / Collaborator | Deletes that **single branch** immediately. |
| `delete+all+dead=<N>` in Issue body | Owner / Member / Collaborator | ⚠️ Nukes **all** branches older than `N` days in one shot. Posts a deletion report. |

> ⚠️ **Warning:** `delete+all+dead` is irreversible. Use with care. Protected branches (`main`, `master`, `develop`, and any `protect+branch`-labelled branches) are always skipped.

---

### 🏷️ Labels Created by the Janitor

| Label | Meaning |
|-------|---------|
| `janitor-paused` | Scheduled scans are paused on this issue. |
| `protected:<branch-name>` | This branch will never be flagged or deleted by the janitor. |

---

## ⚖️ License
MIT
