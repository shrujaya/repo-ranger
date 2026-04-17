import time
import base64
import jwt
import httpx
import os
from typing import Optional, Dict, Any
#updated code

class GitHubAppAuth:
    def __init__(self, app_id: str, private_key: str):
        self.app_id = app_id
        self.private_key = private_key

    def generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication."""
        payload = {
            "iat": int(time.time()) - 60,
            "exp": int(time.time()) + (10 * 60),
            "iss": self.app_id,
        }
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def list_installations(self) -> list:
        """List all installations of this GitHub App."""
        jwt_token = self.generate_jwt()
        url = "https://api.github.com/app/installations"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def get_installation_token(self, installation_id: int) -> str:
        """Exchange JWT for an installation access token."""
        jwt_token = self.generate_jwt()
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            return response.json()["token"]

    async def get_file_sha(
        self, token: str, owner: str, repo: str, path: str
    ) -> Optional[str]:
        """Check if a file exists and return its SHA (None if missing)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()["sha"]
            return None

    async def get_file_content(
        self, token: str, owner: str, repo: str, path: str
    ) -> Optional[str]:
        """Check if a file exists and return its decoded content (None if missing)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if "content" in data:
                    return base64.b64decode(data["content"]).decode()
            return None

    async def list_installation_repos(self, token: str) -> list:
        """List repositories accessible by the given installation token."""
        url = "https://api.github.com/installation/repositories"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json().get("repositories", [])

    async def list_pull_requests(
        self, token: str, owner: str, repo: str, state: str = "open"
    ) -> list:
        """List open pull requests in a repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params={"state": state})
            response.raise_for_status()
            return response.json()

    async def delete_branch(
        self, token: str, owner: str, repo: str, branch: str
    ) -> int:
        """Delete a branch ref from a repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers)
            response.raise_for_status()
            return response.status_code
    async def list_branches(
        self, token: str, owner: str, repo: str
    ) -> list:
        """List all branches in a repository."""
        url = f"https://api.github.com/repos/{owner}/{repo}/branches"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()

    async def create_issue_comment(
        self, token: str, owner: str, repo: str, issue_number: int, body: str
    ) -> dict:
        """Post a comment on an issue or pull request."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json={"body": body})
            if response.status_code >= 400:
                raise Exception(f"Comment creation failed: {response.text}")
            return response.json()

    async def get_issue_labels(
        self, token: str, owner: str, repo: str, issue_number: int
    ) -> list:
        """Return a list of label names on the given issue."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return [lbl["name"] for lbl in response.json()]

    async def add_label(
        self, token: str, owner: str, repo: str, issue_number: int, label: str
    ) -> None:
        """Create a label (if missing) then apply it to the given issue."""
        gh_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            # Ensure the label exists in the repo (idempotent)
            await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/labels",
                headers=gh_headers,
                json={"name": label, "color": "ededed"},
            )
            # Apply it to the issue
            resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels",
                headers=gh_headers,
                json={"labels": [label]},
            )
            if resp.status_code >= 400:
                raise Exception(f"Failed to add label '{label}': {resp.text}")

    async def remove_label(
        self, token: str, owner: str, repo: str, issue_number: int, label: str
    ) -> None:
        """Remove a label from the given issue (no-op if not present)."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            await client.delete(url, headers=headers)  # 404 is fine — label wasn't there

    async def close_issue(
        self, token: str, owner: str, repo: str, issue_number: int
    ) -> None:
        """Close an issue."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.patch(url, headers=headers, json={"state": "closed"})
            if resp.status_code >= 400:
                raise Exception(f"Failed to close issue #{issue_number}: {resp.text}")

    async def compare_branches(
        self, token: str, owner: str, repo: str, base: str, head: str
    ) -> dict:
        """Compare two branches; returns a dict with 'ahead_by', 'behind_by', 'status'."""
        url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base}...{head}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return {"ahead_by": -1, "behind_by": -1, "status": "unknown"}
            data = resp.json()
            return {
                "ahead_by": data.get("ahead_by", 0),
                "behind_by": data.get("behind_by", 0),
                "status": data.get("status", "unknown"),
            }

    async def get_default_branch(
        self, token: str, owner: str, repo: str
    ) -> str:
        """Return the default branch name (usually 'main' or 'master')."""
        url = f"https://api.github.com/repos/{owner}/{repo}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json().get("default_branch", "main")


async def trigger_workflow_dispatch(
    token: str,
    owner: str,
    repo: str,
    workflow_id: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> int:
    """Trigger a workflow_dispatch event on a repository."""
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, json={"ref": ref, "inputs": inputs or {}})
        response.raise_for_status()
        return response.status_code


async def create_file_and_pr(
    token: str,
    owner: str,
    repo: str,
    branch: str,
    path: str,
    content: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
    base_branch: str = "main",
    file_sha: Optional[str] = None,
) -> dict:
    """Create a branch, commit a file, and open a PR."""
    gh_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        # 1. Resolve base branch SHA (fallback to master)
        base_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
            headers=gh_headers,
        )
        if base_resp.status_code != 200:
            base_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/master",
                headers=gh_headers,
            )
            base_branch = "master"
        base_resp.raise_for_status()
        sha = base_resp.json()["object"]["sha"]

        # 2. Create the setup branch
        branch_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=gh_headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if branch_resp.status_code >= 400:
            raise Exception(f"Branch creation failed: {branch_resp.text}")

        # 3. Commit the file (base64-encoded)
        payload = {
            "message": commit_message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if file_sha:
            payload["sha"] = file_sha

        commit_resp = await client.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=gh_headers,
            json=payload,
        )
        if commit_resp.status_code >= 400:
            raise Exception(f"File commit failed: {commit_resp.text}")

        # 4. Open the PR
        pr_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            headers=gh_headers,
            json={"title": pr_title, "body": pr_body, "head": branch, "base": base_branch},
        )
        if pr_resp.status_code >= 400:
            raise Exception(f"PR creation failed: {pr_resp.text}")
            
        return pr_resp.json()
