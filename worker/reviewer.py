import os
import httpx
import json
from groq import AsyncGroq
from .prompts import SYSTEM_REVIEWER_PROMPT

async def run_review(pr_number: int, repo_full_name: str, github_token: str, groq_api_key: str):
    client = AsyncGroq(api_key=groq_api_key)
    
    # 1. Fetch PR Diff
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.diff"
    }
    async with httpx.AsyncClient() as http_client:
        response = await http_client.get(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
            headers=headers
        )
        diff_text = response.text

    # 2. Get AI Review
    # We ask for a JSON object with a 'comments' array
    completion = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_REVIEWER_PROMPT},
            {"role": "user", "content": f"Review this diff for PR #{pr_number}:\n\n{diff_text}"}
        ],
        response_format={"type": "json_object"}
    )
    
    review_data = json.loads(completion.choices[0].message.content)
    comments = review_data.get("comments", [])
    
    # 3. Post Cohesive Review
    post_headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 4. Formulate the Markdown Body
    body_text = "🤖 **RepoRanger AI Code Review**\n\n"
    
    if comments:
        body_text += "I've analyzed your changes for logic, security, and performance. Here is my feedback:\n\n"
        for c in comments:
            path = c.get("path", "file")
            line = c.get("line", "?")
            comment_text = c.get("comment", "")
            if str(line).lower() == "general":
                body_text += f"- **{path}** (General Comment): {comment_text}\n"
            else:
                body_text += f"- **{path}** (Line {line}): {comment_text}\n"
        event_type = "COMMENT"
    else:
        body_text += "✅ **LGTM!**\n\nI've analyzed the architectural changes, logic, and security implications of this PR. Everything looks solid and follows best practices. Keep up the great work!"
        event_type = "APPROVE"

    review_payload = {
        "body": body_text,
        "event": event_type
    }

    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews",
            headers=post_headers,
            json=review_payload
        )
        resp.raise_for_status()

    print(f"Review submitted for PR #{pr_number}")
