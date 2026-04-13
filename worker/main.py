import os
import asyncio
import sys
from .reviewer import run_review
from .janitor import run_janitor

async def main():
    task = os.getenv("INPUT_TASK", "review")
    repo = os.getenv("GITHUB_REPOSITORY")
    github_token = os.getenv("GITHUB_TOKEN")
    groq_api_key = os.getenv("GROQ_API_KEY")
    
    # Internal variables for janitor
    delete_secret = os.getenv("DELETE_SECRET", "ranger-danger")
    dispatcher_url = os.getenv("DISPATCHER_URL", "https://reporanger.vercel.app")
    
    if task == "review":
        pr_number = int(os.getenv("INPUT_PR_NUMBER", "0"))
        if not pr_number:
            print("Error: pr_number input is required for review task.")
            sys.exit(1)
            
        await run_review(pr_number, repo, github_token, groq_api_key)
        
    elif task == "janitor":
        threshold = int(os.getenv("INPUT_DEAD_BRANCH_THRESHOLD", "10"))
        await run_janitor(repo, github_token, delete_secret, dispatcher_url, threshold)
        
    else:
        print(f"Unknown task: {task}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
