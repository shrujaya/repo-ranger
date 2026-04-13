import os
import httpx
import hmac
import hashlib
from datetime import datetime, timedelta

import os
import httpx
import hmac
import hashlib
from datetime import datetime
from .prompts import SYSTEM_JANITOR_PROMPT

async def run_janitor(repo_full_name: str, github_token: str, delete_secret: str, dispatcher_url: str, threshold_days: int = 10):
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Get all branches
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/branches", headers=headers)
        branches = resp.json()
    
    stale_branches = []
    now = datetime.utcnow()
    
    for branch in branches:
        branch_name = branch["name"]
        if branch_name in ["main", "master", "develop"]:
            continue
            
        commit_sha = branch["commit"]["sha"]
        async with httpx.AsyncClient() as client:
            commit_resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/commits/{commit_sha}", headers=headers)
            commit_data = commit_resp.json()
            last_date_str = commit_data["commit"]["committer"]["date"]
            last_date = datetime.strptime(last_date_str, "%Y-%m-%dT%H:%M:%SZ")
            
            if (now - last_date).days > threshold_days:
                owner, repo_name = repo_full_name.split("/")
                token = hmac.new(delete_secret.encode(), f"{owner}/{repo_name}/{branch_name}".encode(), hashlib.sha256).hexdigest()
                delete_url = f"{dispatcher_url}/delete?token={token}&branch={branch_name}&owner={owner}&repo={repo_name}"
                
                stale_branches.append({
                    "name": branch_name,
                    "last_commit": last_date_str,
                    "delete_url": delete_url
                })

    # 2. Check for existing Hygiene Report issue
    report_title = "🧹 RepoRanger: Hygiene Report"
    existing_issue = None
    async with httpx.AsyncClient() as client:
        issues_resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/issues", headers=headers, params={"state": "open"})
        for issue in issues_resp.json():
            if issue["title"] == report_title:
                existing_issue = issue
                break

    # 3. Handle Issue Lifecycle
    if not stale_branches:
        if existing_issue:
            # Auto-Close: Forest Cleaned!
            async with httpx.AsyncClient() as client:
                await client.post(f"{existing_issue['url']}/comments", headers=headers, json={"body": "🎉 **The forest is clean!** All stale branches have been removed. Closing this report."})
                await client.patch(existing_issue["url"], headers=headers, json={"state": "closed"})
            print("Forest is clean. Closed existing report.")
        return

    # Generate issue body
    issue_body = "## 🌳 RepoRanger Hygiene Report\n\nThe following branches haven't been touched in over 10 days. Clean them up to keep the forest healthy!\n\n"
    for b in stale_branches:
        issue_body += f"- **{b['name']}** (Last commit: {b['last_commit']})  \n  [🗑️ Quick Delete]({b['delete_url']})\n"

    async with httpx.AsyncClient() as client:
        if existing_issue:
            # Update existing
            await client.patch(existing_issue["url"], headers=headers, json={"body": issue_body})
            print(f"Updated hygiene report for {repo_full_name}")
        else:
            # Create new
            await client.post(f"https://api.github.com/repos/{repo_full_name}/issues", headers=headers, json={"title": report_title, "body": issue_body})
            print(f"Created new hygiene report for {repo_full_name}")
