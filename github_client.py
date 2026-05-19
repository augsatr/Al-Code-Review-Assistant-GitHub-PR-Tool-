import re
import os
import requests
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PRFile:
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str
    raw_url: str


@dataclass
class PullRequest:
    repo_full: str
    pr_number: int
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    files: list[PRFile] = field(default_factory=list)
    raw_diff: str = ""


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3.diff",
            "User-Agent": "AI-Code-Review-Assistant/1.0",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def _api(self, url: str) -> dict:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _diff(self, url: str) -> str:
        headers = {"Accept": "application/vnd.github.v3.diff"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text

    def parse_pr_url(self, url: str) -> tuple[str, int]:
        m = re.match(
            r"https?://(?:www\.)?github\.com/([^/]+/[^/]+)/pull/(\d+)", url
        )
        if not m:
            raise ValueError(f"Invalid GitHub PR URL: {url}")
        return m.group(1), int(m.group(2))

    def fetch_pr(self, pr_url: str) -> PullRequest:
        repo, num = self.parse_pr_url(pr_url)
        base = f"{self.BASE}/repos/{repo}"

        pr_data = self._api(f"{base}/pulls/{num}")
        files_data = self._api(f"{base}/pulls/{num}/files")
        diff_text = self._diff(f"{base}/pulls/{num}")

        files = []
        for f in files_data:
            files.append(PRFile(
                filename=f["filename"],
                status=f["status"],
                additions=f["additions"],
                deletions=f["deletions"],
                patch=f.get("patch", ""),
                raw_url=f.get("raw_url", ""),
            ))

        return PullRequest(
            repo_full=repo,
            pr_number=num,
            title=pr_data.get("title", ""),
            description=pr_data.get("body", ""),
            author=pr_data.get("user", {}).get("login", ""),
            base_branch=pr_data.get("base", {}).get("ref", ""),
            head_branch=pr_data.get("head", {}).get("ref", ""),
            files=files,
            raw_diff=diff_text,
        )
