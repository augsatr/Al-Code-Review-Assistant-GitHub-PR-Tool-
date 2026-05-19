import argparse
import os
import sys
from flask import Flask, render_template, request, jsonify

from github_client import GitHubClient
from analyzer import analyze_pr, SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO

app = Flask(__name__)
app.secret_key = os.urandom(32).hex()
_token = None


SEVERITY_COLORS = {
    SEVERITY_CRITICAL: "\033[1;31m",
    SEVERITY_WARNING: "\033[1;33m",
    SEVERITY_INFO: "\033[1;34m",
}
RESET = "\033[0m"
BOLD = "\033[1m"


def _fmt(s, color="", bold=False):
    prefix = BOLD if bold else ""
    return f"{prefix}{color}{s}{RESET}"


def _cli_review(pr_url, token=None):
    client = GitHubClient(token=token)
    pr = client.fetch_pr(pr_url)
    report = analyze_pr(pr)

    print()
    print(_fmt(f"{'='*60}", bold=True))
    print(_fmt(f"  AI CODE REVIEW — {pr.repo_full} #{pr.pr_number}", bold=True))
    print(_fmt(f"  {pr.title}", bold=False))
    print(_fmt(f"{'='*60}", bold=True))
    print(f"  Author: {pr.author}")
    print(f"  Branches: {pr.base_branch} ← {pr.head_branch}")
    print(f"  Score: {_fmt(str(report.score), bold=True)}/100")
    print(f"\n  {report.summary}")
    print()

    if report.strengths:
        print(_fmt("  STRENGTHS", bold=True))
        for s in report.strengths:
            print(f"    ✅ {s}")
        print()

    if not report.comments:
        print(_fmt("  No issues found. Great work! 🎉", bold=True))
    else:
        for cat in [SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO]:
            items = [c for c in report.comments if c.severity == cat]
            if not items:
                continue
            label = {"critical": "CRITICAL", "warning": "WARNINGS", "info": "INFO"}[cat]
            color = SEVERITY_COLORS[cat]
            print(_fmt(f"  {label}", bold=True, color=color))
            print(_fmt(f"  {'-'*56}", color=color))
            for c in items:
                icon = {"critical": "🔴", "warning": "⚠️ ", "info": "ℹ️ "}[cat]
                print(f"  {icon} {c.file}:{c.line}")
                print(f"     {_fmt(c.title, bold=True)} ({c.category})")
                print(f"     {c.description}")
                print(f"     {_fmt('➜', bold=True)} {c.suggestion}")
                print()
    return report


def _start_server(port, token=None):
    global _token
    _token = token
    print(f"AI Code Review Assistant → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)


# ── Web routes ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/review", methods=["POST"])
def review():
    pr_url = request.form.get("pr_url", "").strip()
    t = request.form.get("token", "").strip() or _token
    if not pr_url:
        return render_template("error.html", message="Please provide a PR URL.")
    try:
        client = GitHubClient(token=t)
        pr = client.fetch_pr(pr_url)
        report = analyze_pr(pr)
        return render_template("report.html", pr=pr, report=report)
    except Exception as e:
        return render_template("error.html", message=str(e))

@app.route("/api/review", methods=["POST"])
def api_review():
    data = request.get_json(silent=True) or {}
    pr_url = data.get("pr_url", "").strip()
    t = data.get("token", "").strip() or _token
    if not pr_url:
        return jsonify({"error": "pr_url is required"}), 400
    try:
        client = GitHubClient(token=t)
        pr = client.fetch_pr(pr_url)
        report = analyze_pr(pr)
        return jsonify({
            "repo": pr.repo_full,
            "pr_number": pr.pr_number,
            "title": pr.title,
            "score": report.score,
            "summary": report.summary,
            "strengths": report.strengths,
            "comments": [{
                "file": c.file, "line": c.line,
                "severity": c.severity, "category": c.category,
                "title": c.title, "description": c.description,
                "suggestion": c.suggestion,
            } for c in report.comments],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── CLI entry ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="pr-review",
        description="AI Code Review Assistant — Analyze GitHub Pull Requests",
    )
    parser.add_argument("pr_url", nargs="?", help="GitHub Pull Request URL")
    parser.add_argument("--token", "-t", help="GitHub personal access token")
    parser.add_argument("--serve", "-s", action="store_true",
                        help="Start web server instead of CLI review")
    parser.add_argument("--port", "-p", type=int, default=5001,
                        help="Web server port (default: 5001)")

    args = parser.parse_args()

    if args.serve:
        _start_server(args.port, args.token)
    elif args.pr_url:
        _cli_review(args.pr_url, args.token)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
