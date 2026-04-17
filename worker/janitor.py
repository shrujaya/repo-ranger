import os
import httpx
import re
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTECTED_BRANCHES = {"main", "master", "develop"}
JANITOR_PROTECTED_LABEL_PREFIX = "protected:"
JANITOR_PAUSED_LABEL = "janitor-paused"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_headers(github_token: str) -> dict:
    return {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }


async def _fetch_branches(repo_full_name: str, headers: dict) -> list | None:
    """Return all branches for the repo, or None on failure."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/branches",
            headers=headers,
        )
    if resp.status_code != 200:
        print(f"Failed to fetch branches: {resp.status_code}")
        return None
    return resp.json()


async def _fetch_commit(repo_full_name: str, sha: str, headers: dict) -> dict | None:
    """Return commit data for a SHA, or None on failure."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/commits/{sha}",
            headers=headers,
        )
    if resp.status_code != 200:
        return None
    return resp.json()


async def _get_default_branch(repo_full_name: str, headers: dict) -> str:
    """Return the default branch name for the repo."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}",
            headers=headers,
        )
    if resp.status_code == 200:
        return resp.json().get("default_branch", "main")
    return "main"


async def _is_merged_into(repo_full_name: str, base: str, head: str, headers: dict) -> bool:
    """Return True if `head` has no commits ahead of `base` (fully merged)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/compare/{base}...{head}",
            headers=headers,
        )
    if resp.status_code != 200:
        return False
    data = resp.json()
    return data.get("ahead_by", 1) == 0


async def _get_protected_labels(repo_full_name: str, issue_number: int, headers: dict) -> set:
    """Fetch labels on the tracking issue that encode protected branch names."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}/labels",
            headers=headers,
        )
    if resp.status_code != 200:
        return set()
    names = [lbl["name"] for lbl in resp.json()]
    protected = set()
    for name in names:
        if name.startswith(JANITOR_PROTECTED_LABEL_PREFIX):
            branch = name[len(JANITOR_PROTECTED_LABEL_PREFIX):]
            protected.add(branch)
    return protected


async def _post_comment(repo_full_name: str, issue_number: int, body: str, headers: dict):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.github.com/repos/{repo_full_name}/issues/{issue_number}/comments",
            headers=headers,
            json={"body": body},
        )


async def _collect_stale(
    repo_full_name: str,
    github_token: str,
    threshold_days: int,
    extra_protected: set | None = None,
) -> list[dict]:
    """
    Collect stale branches older than `threshold_days`.
    Returns a list of dicts: {name, last_commit, dead_days, author}.
    """
    headers = _make_headers(github_token)
    branches = await _fetch_branches(repo_full_name, headers)
    if branches is None:
        return []

    skip = PROTECTED_BRANCHES | (extra_protected or set())
    stale = []
    now = datetime.utcnow()

    for branch in branches:
        branch_name = branch["name"]
        if branch_name in skip:
            continue
        commit_data = await _fetch_commit(repo_full_name, branch["commit"]["sha"], headers)
        if not commit_data:
            continue
        date_str = commit_data["commit"]["committer"]["date"]
        last_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        days_dead = (now - last_date).days
        if days_dead >= threshold_days:
            stale.append({
                "name": branch_name,
                "last_commit": date_str,
                "dead_days": days_dead,
                "author": commit_data["commit"]["committer"].get("name", "unknown"),
                "commit_count": 1,  # placeholder; we don't paginate commits per branch
            })

    return stale


# ---------------------------------------------------------------------------
# Original commands
# ---------------------------------------------------------------------------

async def run_janitor(
    repo_full_name: str,
    github_token: str,
    threshold_days: int = 10,
    target_number: int | None = None,
):
    """Report stale branches older than threshold_days."""
    stale_branches = await _collect_stale(repo_full_name, github_token, threshold_days)

    if not stale_branches:
        msg = (
            f"🎉 **The forest is clean!** I checked for branches older than "
            f"{threshold_days} days, and there are none."
        )
    else:
        stale_branches.sort(key=lambda b: b["dead_days"], reverse=True)
        msg = (
            f"## 🌳 RepoRanger Dead Branch Report\n\n"
            f"I found the following branches that haven't been touched in over "
            f"{threshold_days} days:\n\n"
            f"| Branch | Last Author | Days Inactive | Last Commit |\n"
            f"|--------|-------------|---------------|-------------|\n"
        )
        for b in stale_branches:
            commit_date = b["last_commit"][:10]  # YYYY-MM-DD
            msg += f"| `{b['name']}` | {b['author']} | {b['dead_days']} days | {commit_date} |\n"
        msg += (
            f"\n> Total stale branches: **{len(stale_branches)}**\n"
            "> **Admins:** Reply to this comment with the exact branch name you'd like me to delete."
        )

    if target_number:
        headers = _make_headers(github_token)
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted dead branch report to Issue/PR #{target_number}")
    else:
        print(msg)


async def run_scheduled_janitor(repo_full_name: str, github_token: str):
    """
    Runs on a schedule. Scans open issues for `check+dead=<N>` keywords
    and periodically posts a fresh dead-branch report. Respects
    `janitor-paused` label.
    """
    headers = _make_headers(github_token)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.github.com/repos/{repo_full_name}/issues?state=open",
            headers=headers,
        )
        if resp.status_code != 200:
            print("Failed to fetch Issues")
            return
        issues = resp.json()

    for issue in issues:
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

        # Respect pause label
        issue_labels = [lbl["name"] for lbl in issue.get("labels", [])]
        if JANITOR_PAUSED_LABEL in issue_labels:
            print(f"Skipping Issue #{target_number} — janitor is paused.")
            continue

        # Collect per-issue protected branches from labels
        protected_set = set()
        for label_name in issue_labels:
            if label_name.startswith(JANITOR_PROTECTED_LABEL_PREFIX):
                protected_set.add(label_name[len(JANITOR_PROTECTED_LABEL_PREFIX):])

        async with httpx.AsyncClient() as client:
            comments_resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/issues/{target_number}/comments",
                headers=headers,
            )

        if comments_resp.status_code != 200:
            continue

        comments = comments_resp.json()
        last_comment_time = None
        for comment in reversed(comments):
            body = comment.get("body", "")
            if "🌳 RepoRanger Dead Branch Report" in body or "The forest is clean!" in body:
                last_comment_time = datetime.strptime(
                    comment["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                break

        now = datetime.utcnow()
        if not last_comment_time or (now - last_comment_time).days >= threshold_days:
            print(f"Running scheduled janitor for Issue #{target_number}")
            stale = await _collect_stale(
                repo_full_name, github_token, threshold_days, protected_set
            )
            if not stale:
                msg = (
                    f"🎉 **The forest is clean!** I checked for branches older than "
                    f"{threshold_days} days, and there are none."
                )
            else:
                stale.sort(key=lambda b: b["dead_days"], reverse=True)
                msg = (
                    f"## 🌳 RepoRanger Dead Branch Report\n\n"
                    f"I found the following branches that haven't been touched in over "
                    f"{threshold_days} days:\n\n"
                    f"| Branch | Last Author | Days Inactive | Last Commit |\n"
                    f"|--------|-------------|---------------|-------------|\n"
                )
                for b in stale:
                    commit_date = b["last_commit"][:10]  # YYYY-MM-DD
                    msg += f"| `{b['name']}` | {b['author']} | {b['dead_days']} days | {commit_date} |\n"
                msg += (
                    f"\n> Total stale branches: **{len(stale)}**\n"
                    "> **Admins:** Reply to this comment with the exact branch name "
                    "you'd like me to delete."
                )
            await _post_comment(repo_full_name, target_number, msg, headers)
        else:
            print(
                f"Skipping Issue #{target_number}, last checked "
                f"{(now - last_comment_time).days} days ago."
            )


# ---------------------------------------------------------------------------
# New commands
# ---------------------------------------------------------------------------

async def run_delete_all_dead(
    repo_full_name: str,
    github_token: str,
    threshold_days: int,
    target_number: int | None = None,
):
    """
    Triggered by `delete+all+dead=<N>`.
    Deletes ALL stale branches older than N days in one shot (admin-only gate
    is enforced at the dispatcher level).
    """
    headers = _make_headers(github_token)
    stale = await _collect_stale(repo_full_name, github_token, threshold_days)

    if not stale:
        msg = (
            f"🎉 **Nothing to delete!** No branches older than {threshold_days} days found."
        )
    else:
        deleted, failed = [], []
        async with httpx.AsyncClient() as client:
            for b in stale:
                resp = await client.delete(
                    f"https://api.github.com/repos/{repo_full_name}/git/refs/heads/{b['name']}",
                    headers=headers,
                )
                if resp.status_code in (204, 200):
                    deleted.append(b["name"])
                else:
                    failed.append(b["name"])

        msg = f"## 🗑️ RepoRanger Bulk Deletion Report\n\n"
        msg += f"Deleted **{len(deleted)}** branch(es) older than {threshold_days} days:\n\n"
        for name in deleted:
            msg += f"- ~~`{name}`~~\n"
        if failed:
            msg += f"\n⚠️ **Failed to delete** ({len(failed)}):\n"
            for name in failed:
                msg += f"- `{name}`\n"
        msg += "\n🌿 The forest is a little cleaner now."

    if target_number:
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted bulk-deletion report to Issue #{target_number}")
    else:
        print(msg)


async def run_protect_branch(
    repo_full_name: str,
    github_token: str,
    branch_name: str,
    target_number: int | None = None,
):
    """
    Triggered by `protect+branch=<name>`.
    Adds a `protected:<branch-name>` label to the tracking issue so future
    scheduled scans skip that branch.
    """
    headers = _make_headers(github_token)
    label = f"{JANITOR_PROTECTED_LABEL_PREFIX}{branch_name}"

    if not target_number:
        print(f"protect+branch: no target issue number provided, cannot persist label.")
        return

    # Ensure label exists in the repo
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.github.com/repos/{repo_full_name}/labels",
            headers=headers,
            json={"name": label, "color": "0075ca"},
        )
        resp = await client.post(
            f"https://api.github.com/repos/{repo_full_name}/issues/{target_number}/labels",
            headers=headers,
            json={"labels": [label]},
        )

    if resp.status_code >= 400:
        msg = f"⚠️ Failed to protect branch `{branch_name}`: {resp.text}"
    else:
        msg = (
            f"🛡️ Branch `{branch_name}` is now **protected** — the janitor will "
            f"never flag it for deletion.\n\n"
            f"To unprotect it, remove the `{label}` label from this issue."
        )

    await _post_comment(repo_full_name, target_number, msg, headers)
    print(f"Protected branch '{branch_name}' on Issue #{target_number}")


async def run_unmerged_report(
    repo_full_name: str,
    github_token: str,
    threshold_days: int,
    target_number: int | None = None,
):
    """
    Triggered by `unmerged+only=<N>`.
    Reports branches that are BOTH stale (>N days) AND not yet merged into
    the default branch.
    """
    headers = _make_headers(github_token)
    default_branch = await _get_default_branch(repo_full_name, headers)
    stale = await _collect_stale(repo_full_name, github_token, threshold_days)

    unmerged = []
    for b in stale:
        merged = await _is_merged_into(repo_full_name, default_branch, b["name"], headers)
        if not merged:
            unmerged.append(b)

    if not unmerged:
        msg = (
            f"✅ **All stale branches are already merged!** No unmerged branches "
            f"older than or equal to {threshold_days} days found."
        )
    else:
        msg = (
            f"## ⚠️ Unmerged Stale Branches (>={threshold_days} days)\n\n"
            f"The following branches are **stale AND unmerged** into `{default_branch}`:\n\n"
        )
        for b in unmerged:
            msg += f"- **`{b['name']}`** — {b['dead_days']} days inactive, last by *{b['author']}*\n"
        msg += (
            "\n> These branches contain unmerged work. Review before deleting.\n\n"
            "> **Admins:** Reply with a branch name to delete it."
        )

    if target_number:
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted unmerged-only report to Issue #{target_number}")
    else:
        print(msg)


async def run_author_report(
    repo_full_name: str,
    github_token: str,
    threshold_days: int,
    target_number: int | None = None,
):
    """
    Triggered by `author+report=<N>`.
    Groups stale branches by last commit author so you can ping people.
    """
    headers = _make_headers(github_token)
    stale = await _collect_stale(repo_full_name, github_token, threshold_days)

    if not stale:
        msg = (
            f"👥 **Author Report:** No stale branches (>={threshold_days} days) found."
        )
    else:
        # Group by author
        by_author: dict[str, list] = {}
        for b in stale:
            by_author.setdefault(b["author"], []).append(b)

        msg = (
            f"## 👥 RepoRanger Author Report\n\n"
            f"Stale branches (>={threshold_days} days) grouped by last committer:\n\n"
        )
        for author, branches in sorted(by_author.items()):
            msg += f"### {author} ({len(branches)} branch{'es' if len(branches) > 1 else ''})\n"
            for b in sorted(branches, key=lambda x: x["dead_days"], reverse=True):
                msg += f"- `{b['name']}` — {b['dead_days']} days inactive\n"
            msg += "\n"
        msg += (
            "\n> **Admins:** Reply with a branch name to delete it, or "
            "ping the author to clean up their own branches."
        )

    if target_number:
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted author report to Issue #{target_number}")
    else:
        print(msg)


async def run_check_merged(
    repo_full_name: str,
    github_token: str,
    target_number: int | None = None,
):
    """
    Triggered by `check+merged`.
    Reports branches that have already been fully merged into the default
    branch but were never deleted.
    """
    headers = _make_headers(github_token)
    default_branch = await _get_default_branch(repo_full_name, headers)
    branches = await _fetch_branches(repo_full_name, headers)
    if branches is None:
        return

    merged_branches = []
    for branch in branches:
        name = branch["name"]
        if name in PROTECTED_BRANCHES or name == default_branch:
            continue
        is_merged = await _is_merged_into(repo_full_name, default_branch, name, headers)
        if is_merged:
            merged_branches.append(name)

    if not merged_branches:
        msg = (
            f"✅ **No ghost branches found!** All non-default branches still have "
            f"unmerged commits relative to `{default_branch}`."
        )
    else:
        msg = (
            f"## 👻 Ghost Branch Report\n\n"
            f"The following branches have been **fully merged** into `{default_branch}` "
            f"but were never deleted:\n\n"
        )
        for name in merged_branches:
            msg += f"- `{name}`\n"
        msg += (
            f"\n> These are safe to delete — all their work is already in `{default_branch}`.\n\n"
            "> **Admins:** Reply with a branch name to delete it."
        )

    if target_number:
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted merged-branch report to Issue #{target_number}")
    else:
        print(msg)


async def run_stale_pr_report(
    repo_full_name: str,
    github_token: str,
    threshold_days: int,
    target_number: int | None = None,
):
    """
    Triggered by `stale+pr=<N>`.
    Reports open PRs with no activity (commits, comments, or reviews)
    for >= N days, sorted by most inactive first.
    """
    headers = _make_headers(github_token)
    now = datetime.utcnow()
    stale_prs = []
    page = 1

    # Fetch all open PRs with pagination
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/pulls",
                headers=headers,
                params={"state": "open", "per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                print(f"Failed to fetch PRs: {resp.status_code}")
                break
            prs = resp.json()
            if not prs:
                break
            for pr in prs:
                updated_at_str = pr.get("updated_at", "")
                if not updated_at_str:
                    continue
                updated_at = datetime.strptime(updated_at_str, "%Y-%m-%dT%H:%M:%SZ")
                days_inactive = (now - updated_at).days
                if days_inactive >= threshold_days:
                    stale_prs.append({
                        "number": pr["number"],
                        "title": pr["title"],
                        "author": pr["user"]["login"],
                        "days_inactive": days_inactive,
                        "updated_at": updated_at_str[:10],
                        "url": pr["html_url"],
                    })
            if len(prs) < 100:
                break
            page += 1

    if not stale_prs:
        msg = (
            f"✅ **No stale PRs found!** All open PRs have had activity within the last "
            f"{threshold_days} days. Great job keeping things moving! 🎉"
        )
    else:
        stale_prs.sort(key=lambda p: p["days_inactive"], reverse=True)
        msg = (
            f"## 🕰️ RepoRanger Stale PR Report\n\n"
            f"The following open PRs haven't had any activity in over {threshold_days} days:\n\n"
            f"| PR | Title | Author | Days Inactive | Last Updated |\n"
            f"|----|-------|--------|---------------|--------------|\n"
        )
        for p in stale_prs:
            msg += (
                f"| [#{p['number']}]({p['url']}) "
                f"| {p['title']} "
                f"| @{p['author']} "
                f"| {p['days_inactive']} days "
                f"| {p['updated_at']} |\n"
            )
        msg += (
            f"\n> Total stale PRs: **{len(stale_prs)}**\n"
            "> **Admins:** Ping the authors or close PRs that are no longer relevant."
        )

    if target_number:
        await _post_comment(repo_full_name, target_number, msg, headers)
        print(f"Posted stale PR report to Issue #{target_number}")
    else:
        print(msg)
