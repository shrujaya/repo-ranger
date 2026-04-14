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
        model="llama-3.1-8b-instant",
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
    
    # If no specific comments, post a general summary
    review_payload = {
        "body": "🤖 **RepoRanger AI Code Review**\n\nI've analyzed your changes for logic, security, and performance. See my inline feedback below.",
        "event": "COMMENT",
        "comments": comments
    }
    
    if not comments:
        review_payload["body"] = "🤖 **RepoRanger AI Code Review**\n\nLGTM! I've analyzed the architectural changes and everything looks solid. Keep up the great work!"
        review_payload["event"] = "APPROVE"
        del review_payload["comments"]

    async with httpx.AsyncClient() as http_client:
        await http_client.post(
            f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews",
            headers=post_headers,
            json=review_payload
        )

    print(f"Review submitted for PR #{pr_number}")
