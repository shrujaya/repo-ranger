import os
import hmac
import hashlib
import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse
from typing import Optional
import re

# Vercel runs files in api/ at the repo root, so we do a package-relative import
from .github_api import GitHubAppAuth, trigger_workflow_dispatch, create_file_and_pr

app = FastAPI(title="RepoRanger Dispatcher")

# ---------------------------------------------------------------------------
# Config (populated from Vercel Environment Variables)
# ---------------------------------------------------------------------------
APP_ID = os.getenv("APP_ID", "")
PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
DELETE_SECRET = os.getenv("DELETE_SECRET", "ranger-danger")

# Template path is relative to repo root (Vercel makes repo root the cwd)
_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "..", "templates", "ai-bot.yml")

auth = GitHubAppAuth(APP_ID, PRIVATE_KEY) if APP_ID and PRIVATE_KEY else None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_signature(payload_body: bytes, signature_header: Optional[str]) -> bool:
    """Verify the X-Hub-Signature-256 header from GitHub."""
    if not WEBHOOK_SECRET:
        return True
    if not signature_header:
        return False
    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=payload_body, digestmod=hashlib.sha256)
    expected = "sha256=" + mac.hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _make_delete_token(owner: str, repo: str, branch: str) -> str:
    return hmac.new(
        DELETE_SECRET.encode(), f"{owner}/{repo}/{branch}".encode(), hashlib.sha256
    ).hexdigest()


def _load_template() -> str:
    try:
        with open(_TEMPLATE_PATH) as f:
            return f.read()
    except FileNotFoundError:
        return "name: RepoRanger\non: [workflow_dispatch]\n"


async def _apply_to_tracking_issues(
    token: str, owner: str, repo: str, action: str, auth_obj
) -> list[int]:
    """
    Scan open issues for `check+dead=` tracking issues and apply a
    pause / resume / stop action to each one.  Returns list of affected
    issue numbers.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    affected: list[int] = []

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=100",
            headers=headers,
        )
        if resp.status_code != 200:
            return affected
        issues = resp.json()

    for issue in issues:
        if "pull_request" in issue:
            continue
        text = (issue.get("title") or "") + "\n" + (issue.get("body") or "")
        if not re.search(r'check\+dead=\d+', text, re.IGNORECASE):
            continue

        num = issue["number"]

        if action == "pause":
            await auth_obj.add_label(token, owner, repo, num, "janitor-paused")
            await auth_obj.create_issue_comment(
                token, owner, repo, num,
                "⏸️ Janitor **paused** on this issue (triggered from a separate issue)."
            )
            affected.append(num)

        elif action == "resume":
            labels = [lbl["name"] for lbl in issue.get("labels", [])]
            if "janitor-paused" in labels:
                await auth_obj.remove_label(token, owner, repo, num, "janitor-paused")
                await auth_obj.create_issue_comment(
                    token, owner, repo, num,
                    "▶️ Janitor **resumed** on this issue (triggered from a separate issue)."
                )
                affected.append(num)

        elif action == "stop":
            await auth_obj.create_issue_comment(
                token, owner, repo, num,
                "🛑 Janitor **stopped** on this issue (triggered from a separate issue). Closing."
            )
            await auth_obj.close_issue(token, owner, repo, num)
            affected.append(num)

    return affected


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def health():
    return {"status": "RepoRanger is on duty 🌳"}


@app.post("/webhook")
async def webhook_handler(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
):
    try:
        payload_body = await request.body()
        if not _verify_signature(payload_body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid signature")

        if not auth:
            raise HTTPException(status_code=500, detail="GitHub App not configured")

        event = await request.json()
        action = event.get("action")

        messages = []
        
        # --- App installation → onboarding PR ---
        if "installation" in event and action == "created" and "comment" not in event:
            installation_id = event["installation"]["id"]
            for repo in event.get("repositories", []):
                owner, repo_name = repo["full_name"].split("/")
                msg = await _handle_onboarding(installation_id, owner, repo_name)
                messages.append(msg)
                
        # --- Repositories added to existing installation → onboarding PR ---
        elif "installation" in event and action == "added":
            installation_id = event["installation"]["id"]
            for repo in event.get("repositories_added", []):
                owner, repo_name = repo["full_name"].split("/")
                msg = await _handle_onboarding(installation_id, owner, repo_name)
                messages.append(msg)

        # --- PR opened/reopened/sync → trigger the worker ---
        elif "pull_request" in event and action in ["opened", "reopened", "synchronize"]:
            installation_id = event["installation"]["id"]
            owner = event["repository"]["owner"]["login"]
            repo_name = event["repository"]["name"]
            pr_number = event["pull_request"]["number"]
            token = await auth.get_installation_token(installation_id)
            
            await trigger_workflow_dispatch(
                token, owner, repo_name, "ai-bot.yml", "main",
                inputs={"task": "review", "target_number": str(pr_number)},
            )
            messages.append(f"Triggered AI review worker for PR #{pr_number}")

        # --- Issue opened → keyword parser ---
        elif "issue" in event and action == "opened" and "pull_request" not in event.get("issue", {}):
            installation_id = event["installation"]["id"]
            owner = event["repository"]["owner"]["login"]
            repo_name = event["repository"]["name"]
            issue_number = event["issue"]["number"]
            issue_body = event["issue"].get("body") or ""
            issue_title = event["issue"].get("title") or ""
            token = await auth.get_installation_token(installation_id)

            text_to_search = issue_title + "\n" + issue_body

            # ── existing commands ──────────────────────────────────────────
            match_manual = re.search(r'dead\+branches=(\d+)', text_to_search, re.IGNORECASE)
            match_cron   = re.search(r'check\+dead=(\d+)',    text_to_search, re.IGNORECASE)

            # ── new commands ───────────────────────────────────────────────
            match_delete_all  = re.search(r'delete\+all\+dead=(\d+)',           text_to_search, re.IGNORECASE)
            match_protect     = re.search(r'protect\+branch=([\w/._-]+)',        text_to_search, re.IGNORECASE)
            match_unmerged    = re.search(r'unmerged\+only=(\d+)',               text_to_search, re.IGNORECASE)
            match_author      = re.search(r'author\+report=(\d+)',              text_to_search, re.IGNORECASE)
            match_check_merged= re.search(r'check\+merged',                     text_to_search, re.IGNORECASE)

            if match_manual:
                days = match_manual.group(1)
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "janitor", "target_number": str(issue_number), "dead_branch_threshold": days},
                )
                messages.append(f"Triggered manual dead-branch check for {days} days on Issue #{issue_number}")

            elif match_cron:
                days = match_cron.group(1)
                await auth.create_issue_comment(
                    token, owner, repo_name, issue_number,
                    f"✅ Understood! I will check this repository for dead branches older than {days} days on a recurring schedule and report back here."
                )
                messages.append(f"Acknowledged scheduled dead-branch check for {days} days on Issue #{issue_number}")

            elif match_delete_all:
                days = match_delete_all.group(1)
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "delete_all_dead", "target_number": str(issue_number), "dead_branch_threshold": days},
                )
                messages.append(f"Triggered bulk deletion of branches older than {days} days on Issue #{issue_number}")

            elif match_protect:
                branch_name = match_protect.group(1)
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "protect_branch", "target_number": str(issue_number), "branch_name": branch_name},
                )
                messages.append(f"Triggered protect-branch for '{branch_name}' on Issue #{issue_number}")

            elif match_unmerged:
                days = match_unmerged.group(1)
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "unmerged_report", "target_number": str(issue_number), "dead_branch_threshold": days},
                )
                messages.append(f"Triggered unmerged-only report (>{days} days) on Issue #{issue_number}")

            elif match_author:
                days = match_author.group(1)
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "author_report", "target_number": str(issue_number), "dead_branch_threshold": days},
                )
                messages.append(f"Triggered author report (>{days} days) on Issue #{issue_number}")

            elif match_check_merged:
                await trigger_workflow_dispatch(
                    token, owner, repo_name, "ai-bot.yml", "main",
                    inputs={"task": "check_merged", "target_number": str(issue_number)},
                )
                messages.append(f"Triggered merged-but-not-deleted check on Issue #{issue_number}")

            # ── scheduling control via issue title/body ───────────────────
            elif re.search(r'pause\+janitor', text_to_search, re.IGNORECASE):
                # Find all open tracking issues with check+dead and pause them
                affected = await _apply_to_tracking_issues(
                    token, owner, repo_name, "pause", auth
                )
                if affected:
                    summary = ", ".join(f"#{n}" for n in affected)
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        f"⏸️ Janitor **paused** on {len(affected)} tracking issue(s): {summary}\n\n"
                        f"Open a new issue with `resume+janitor` to resume, or comment `resume+janitor` on the tracking issue directly."
                    )
                else:
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "⚠️ No active janitor tracking issues found (issues containing `check+dead=<N>`)."
                    )
                messages.append(f"Pause-janitor via Issue #{issue_number}, affected: {affected}")

            elif re.search(r'resume\+janitor', text_to_search, re.IGNORECASE):
                affected = await _apply_to_tracking_issues(
                    token, owner, repo_name, "resume", auth
                )
                if affected:
                    summary = ", ".join(f"#{n}" for n in affected)
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        f"▶️ Janitor **resumed** on {len(affected)} tracking issue(s): {summary}\n\n"
                        f"Scheduled reports will continue on the next run."
                    )
                else:
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "⚠️ No paused janitor tracking issues found."
                    )
                messages.append(f"Resume-janitor via Issue #{issue_number}, affected: {affected}")

            elif re.search(r'stop\+janitor', text_to_search, re.IGNORECASE):
                affected = await _apply_to_tracking_issues(
                    token, owner, repo_name, "stop", auth
                )
                if affected:
                    summary = ", ".join(f"#{n}" for n in affected)
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        f"🛑 Janitor **stopped**. Closed {len(affected)} tracking issue(s): {summary}\n\n"
                        f"No more scheduled reports will be posted."
                    )
                else:
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "⚠️ No active janitor tracking issues found to stop."
                    )
                messages.append(f"Stop-janitor via Issue #{issue_number}, affected: {affected}")

        # --- Issue Comment created → Branch Deletion + Pause/Resume/Stop ---
        elif "comment" in event and action == "created":
            comment_body = event["comment"]["body"].strip()
            author_association = event["comment"]["author_association"]
            # Only allow privileged actions from owners/members/collaborators
            if author_association in ["OWNER", "MEMBER", "COLLABORATOR"]:
                installation_id = event["installation"]["id"]
                owner = event["repository"]["owner"]["login"]
                repo_name = event["repository"]["name"]
                issue_number = event["issue"]["number"]

                token = await auth.get_installation_token(installation_id)

                # ── Scheduling control commands ────────────────────────────
                if re.fullmatch(r'pause\+janitor', comment_body, re.IGNORECASE):
                    await auth.add_label(token, owner, repo_name, issue_number, "janitor-paused")
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "⏸️ Janitor **paused**. I won't post any more scheduled reports on this issue. Reply `resume+janitor` to wake me back up."
                    )
                    messages.append(f"Paused janitor on Issue #{issue_number}")

                elif re.fullmatch(r'resume\+janitor', comment_body, re.IGNORECASE):
                    await auth.remove_label(token, owner, repo_name, issue_number, "janitor-paused")
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "▶️ Janitor **resumed**. I'll continue posting scheduled reports."
                    )
                    messages.append(f"Resumed janitor on Issue #{issue_number}")

                elif re.fullmatch(r'stop\+janitor', comment_body, re.IGNORECASE):
                    await auth.create_issue_comment(
                        token, owner, repo_name, issue_number,
                        "🛑 Janitor **stopped**. Closing this tracking issue. No more reports will be posted."
                    )
                    await auth.close_issue(token, owner, repo_name, issue_number)
                    messages.append(f"Stopped and closed janitor Issue #{issue_number}")

                # ── Branch deletion (existing) ─────────────────────────────
                else:
                    branches = await auth.list_branches(token, owner, repo_name)
                    branch_names = [b["name"] for b in branches]

                    if comment_body in branch_names:
                        try:
                            await auth.delete_branch(token, owner, repo_name, comment_body)
                            await auth.create_issue_comment(
                                token, owner, repo_name, issue_number,
                                f"✅ Success! Branch `{comment_body}` has been permanently removed."
                            )
                            messages.append(f"Admin deleted branch: {comment_body}")
                        except Exception as e:
                            await auth.create_issue_comment(
                                token, owner, repo_name, issue_number,
                                f"⚠️ Failed to delete branch `{comment_body}`. Check permissions.\n`{str(e)}`"
                            )
                            messages.append(f"Failed to delete branch: {comment_body}")

        return {"status": "accepted", "details": messages}
    except Exception as e:
        import traceback
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={
            "error": str(e),
            "traceback": traceback.format_exc()
        })


async def _handle_onboarding(installation_id: int, owner: str, repo: str) -> str:
    """Idempotent: open the Welcome PR only if neither the file nor the PR exist."""
    token = await auth.get_installation_token(installation_id)

    # Guard 1 – workflow file already committed
    if await auth.get_file_sha(token, owner, repo, ".github/workflows/ai-bot.yml"):
        return f"[onboarding] ai-bot.yml already exists in {owner}/{repo}, skipping."

    # Guard 2 – setup PR already open
    open_prs = await auth.list_pull_requests(token, owner, repo)
    if any(pr["title"] == "🤖 Setup: Initialize RepoRanger" for pr in open_prs):
        return f"[onboarding] Setup PR already open for {owner}/{repo}, skipping."

    await create_file_and_pr(
        token, owner, repo,
        branch="setup/reporanger-init",
        path=".github/workflows/ai-bot.yml",
        content=_load_template(),
        commit_message="🤖 chore: add RepoRanger workflow",
        pr_title="🤖 Setup: Initialize RepoRanger",
        pr_body=(
            "👋 **Welcome to RepoRanger!**\n\n"
            "I've added `.github/workflows/ai-bot.yml` to this branch. "
            "Merge this PR to activate AI-powered PR reviews and branch hygiene.\n\n"
            "> **Action Required:** Add `GROQ_API_KEY` to this repository's "
            "[Secrets](../../settings/secrets/actions) before merging."
        ),
    )
    return f"Successfully initiated '🤖 Setup: Initialize RepoRanger' on {owner}/{repo}"


@app.get("/delete", response_class=HTMLResponse)
async def delete_confirmation(token: str, branch: str, owner: str, repo: str):
    """Serve the human-readable confirmation page for branch deletion."""
    if not hmac.compare_digest(token, _make_delete_token(owner, repo, branch)):
        raise HTTPException(status_code=401, detail="Invalid token")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RepoRanger – Delete branch</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f0f4f0;
           display: grid; place-items: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #fff; padding: 2rem 2.5rem; border-radius: 14px;
             border: 2px solid #2d5a27; max-width: 420px; text-align: center; }}
    h2 {{ color: #2d5a27; margin-top: 0; }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 4px; }}
    .btn-danger {{ background: #e74c3c; color: #fff; border: none;
                  padding: 10px 22px; border-radius: 6px; cursor: pointer;
                  font-size: 1rem; }}
    .btn-cancel {{ margin-left: 12px; color: #7f8c8d; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>🌳 RepoRanger Janitor</h2>
    <p>Delete branch <code>{branch}</code> from <strong>{owner}/{repo}</strong>?</p>
    <form action="/delete/execute" method="post">
      <input type="hidden" name="token" value="{token}">
      <input type="hidden" name="branch" value="{branch}">
      <input type="hidden" name="owner" value="{owner}">
      <input type="hidden" name="repo" value="{repo}">
      <button class="btn-danger" type="submit">Yes, delete it</button>
      <a class="btn-cancel" href="javascript:history.back()">Cancel</a>
    </form>
  </div>
</body>
</html>"""


@app.post("/delete/execute", response_class=HTMLResponse)
async def execute_delete(request: Request):
    """Verify the signed token and delete the branch via GitHub API."""
    form = await request.form()
    token = form.get("token", "")
    branch = form.get("branch", "")
    owner = form.get("owner", "")
    repo = form.get("repo", "")

    if not hmac.compare_digest(token, _make_delete_token(owner, repo, branch)):
        raise HTTPException(status_code=401, detail="Invalid token")

    if not auth:
        raise HTTPException(status_code=500, detail="GitHub App not configured")

    # Look up the installation for this repo
    jwt_token = auth.generate_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/installation",
            headers={"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Installation not found for this repo")

    install_token = await auth.get_installation_token(resp.json()["id"])
    await auth.delete_branch(install_token, owner, repo, branch)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>RepoRanger – Branch deleted</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f0f4f0;
           display: grid; place-items: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #fff; padding: 2rem 2.5rem; border-radius: 14px;
             border: 2px solid #2d5a27; max-width: 420px; text-align: center; }}
    h2 {{ color: #2d5a27; margin-top: 0; }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>✅ Branch Deleted</h2>
    <p><code>{branch}</code> has been removed from <strong>{owner}/{repo}</strong>.</p>
    <p>The forest is a little cleaner now. 🌿</p>
  </div>
</body>
</html>"""
