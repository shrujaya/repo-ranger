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

import re
from datetime import datetime

async def run_janitor(repo_full_name: str, github_token: str, threshold_days: int = 10, target_number: int = None):
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 1. Get all branches
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/branches", headers=headers)
        if resp.status_code != 200:
            print("Failed to fetch branches")
            return
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
            if commit_resp.status_code != 200:
                continue
            commit_data = commit_resp.json()
            last_date_str = commit_data["commit"]["committer"]["date"]
            last_date = datetime.strptime(last_date_str, "%Y-%m-%dT%H:%M:%SZ")
            
            if (now - last_date).days > threshold_days:
                stale_branches.append({
                    "name": branch_name,
                    "last_commit": last_date_str,
                    "dead_days": (now - last_date).days
                })

    if not stale_branches:
        msg = f"🎉 **The forest is clean!** I checked for branches older than {threshold_days} days, and there are none."
    else:
        msg = f"## 🌳 RepoRanger Dead Branch Report\n\nI found the following branches that haven't been touched in over {threshold_days} days:\n\n"
        for b in stale_branches:
            msg += f"- **{b['name']}** (dead for {b['dead_days']} days)\n"
        msg += "\n> **Admins:** Reply to this comment with the exact branch name you'd like me to delete."

    async with httpx.AsyncClient() as client:
        if target_number:
            # Post directly to Issue/PR
            await client.post(f"https://api.github.com/repos/{repo_full_name}/issues/{target_number}/comments", headers=headers, json={"body": msg})
            print(f"Posted dead branch report to Issue/PR #{target_number}")
        else:
            print(msg)


async def run_scheduled_janitor(repo_full_name: str, github_token: str):
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # List open Issues
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/issues?state=open", headers=headers)
        if resp.status_code != 200:
            print("Failed to fetch Issues")
            return
        issues = resp.json()
        
    for issue in issues:
        # Ignore pull requests
        if "pull_request" in issue:
            continue
            
        target_number = issue["number"]
        body_text = issue.get("body") or ""
        title_text = issue.get("title") or ""
        text = title_text + "\n" + body_text
        
        match = re.search(r'check\+dead=(\d+)', text, re.IGNORECASE)
        if not match:
            continue
            
        threshold_days = int(match.group(1))
        
        # We need to know if we've commented recently on this Issue.
        comments_resp = await client.get(f"https://api.github.com/repos/{repo_full_name}/issues/{target_number}/comments", headers=headers)
        if comments_resp.status_code != 200:
            continue
            
        comments = comments_resp.json()
        
        # Find the latest comment made by us
        last_comment_time = None
        for comment in reversed(comments):
            if "🌳 RepoRanger Dead Branch Report" in comment.get("body", "") or "The forest is clean!" in comment.get("body", ""):
                last_comment_time = datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                break
                
        now = datetime.utcnow()
        if not last_comment_time or (now - last_comment_time).days >= threshold_days:
            # Time to run report for this Issue!
            print(f"Running scheduled janitor for Issue #{target_number}")
            await run_janitor(repo_full_name, github_token, threshold_days, target_number)
        else:
            print(f"Skipping Issue #{target_number}, last checked {(now - last_comment_time).days} days ago.")
