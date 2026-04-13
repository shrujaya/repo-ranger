import time
import base64
import jwt
import httpx
import os
from typing import Optional, Dict, Any


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
        await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/git/refs",
            headers=gh_headers,
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )

        # 3. Commit the file (base64-encoded)
        await client.put(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=gh_headers,
            json={
                "message": commit_message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch,
            },
        )

        # 4. Open the PR
        pr_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            headers=gh_headers,
            json={"title": pr_title, "body": pr_body, "head": branch, "base": base_branch},
        )
        pr_resp.raise_for_status()
        return pr_resp.json()
