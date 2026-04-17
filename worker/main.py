import os
import asyncio
import sys
from .reviewer import run_review
from .janitor import (
    run_janitor,
    run_scheduled_janitor,
    run_delete_all_dead,
    run_protect_branch,
    run_unmerged_report,
    run_author_report,
    run_check_merged,
    run_stale_pr_report,
    run_help,
)


async def main():
    task = os.getenv("INPUT_TASK", "review")
    repo = os.getenv("GITHUB_REPOSITORY")
    github_token = os.getenv("GITHUB_TOKEN")
    groq_api_key = os.getenv("GROQ_API_KEY")

    # Shared janitor env
    target_number_raw = os.getenv("INPUT_TARGET_NUMBER", "")
    target_number = int(target_number_raw) if target_number_raw else None
    threshold = int(os.getenv("INPUT_DEAD_BRANCH_THRESHOLD", "10"))

    # Validate required config
    if not github_token:
        print("❌ Error: GITHUB_TOKEN is missing. Check your workflow permissions.")
        sys.exit(1)
    
    if task == "review" and not groq_api_key:
        print("❌ Error: GROQ_API_KEY is missing. Add it to your repository secrets.")
        sys.exit(1)

    # ------------------------------------------------------------------ #
    if task == "review":
        pr_number = target_number or 0
        if not pr_number:
            print("Error: target_number input is required for review task.")
            sys.exit(1)
        await run_review(pr_number, repo, github_token, groq_api_key)

    # --- original janitor ---
    elif task == "janitor":
        await run_janitor(repo, github_token, threshold, target_number)

    elif task == "scheduled_janitor":
        await run_scheduled_janitor(repo, github_token)

    # --- new janitor commands ---
    elif task == "delete_all_dead":
        await run_delete_all_dead(repo, github_token, threshold, target_number)

    elif task == "protect_branch":
        branch_name = os.getenv("INPUT_BRANCH_NAME", "")
        if not branch_name:
            print("Error: INPUT_BRANCH_NAME is required for protect_branch task.")
            sys.exit(1)
        await run_protect_branch(repo, github_token, branch_name, target_number)

    elif task == "unmerged_report":
        await run_unmerged_report(repo, github_token, threshold, target_number)

    elif task == "author_report":
        await run_author_report(repo, github_token, threshold, target_number)

    elif task == "check_merged":
        await run_check_merged(repo, github_token, target_number)

    elif task == "help":
        await run_help(repo, github_token, target_number)

    elif task == "stale_pr_report":
        await run_stale_pr_report(repo, github_token, threshold, target_number)

    else:
        print(f"Unknown task: {task}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
