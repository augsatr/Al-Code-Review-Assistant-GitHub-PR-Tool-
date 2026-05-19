import ast
import re
from dataclasses import dataclass, field
from typing import Optional


SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


@dataclass
class ReviewComment:
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggestion: str


@dataclass
class ReviewReport:
    summary: str
    score: int
    comments: list[ReviewComment] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == SEVERITY_CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == SEVERITY_WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for c in self.comments if c.severity == SEVERITY_INFO)


class CodeAnalyzer:
    def __init__(self):
        self.comments: list[ReviewComment] = []
        self.strengths: list[str] = []

    def analyze(self, files) -> ReviewReport:
        for f in files:
            if not f.patch:
                continue
            lines = f.patch.split("\n")
            self._analyze_file(f.filename, f.patch, lines)

        score = self._compute_score()
        summary = self._build_summary(files)
        return ReviewReport(
            summary=summary,
            score=score,
            comments=self.comments,
            strengths=self.strengths,
        )

    def _compute_score(self) -> int:
        deductions = (
            self.critical_count * 15
            + self.warning_count * 5
            + self.info_count * 2
        )
        return max(0, min(100, 100 - deductions))

    def _build_summary(self, files) -> str:
        total_added = sum(f.additions for f in files)
        total_deleted = sum(f.deletions for f in files)
        changed = len(files)
        return (
            f"Reviewed {changed} file(s) "
            f"(+{total_added}/-{total_deleted} lines). "
            f"Found {len(self.comments)} issue(s) "
            f"({self.critical_count} critical, "
            f"{self.warning_count} warnings, "
            f"{self.info_count} info)."
        )

    def _parse_linenos(self, line: str) -> Optional[tuple[int, int]]:
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if m:
            return int(m.group(1)), int(m.group(1))
        return None

    def _track_line_numbers(self, lines: list[str]):
        result = {}
        new_line = 0
        for i, line in enumerate(lines):
            lineno = self._parse_linenos(line)
            if lineno:
                new_line = lineno[0]
            elif line.startswith("+") and not line.startswith("+++"):
                result[i] = new_line
                new_line += 1
            elif not line.startswith("-"):
                new_line += 1
        return result

    def _analyze_file(self, filename: str, patch: str, lines: list[str]):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        lineno_map = self._track_line_numbers(lines)

        added_lines = []
        for i, line in enumerate(lines):
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append((i, line[1:], lineno_map.get(i, 0)))

        if ext in ("py",):
            self._analyze_python(filename, added_lines)
        elif ext in ("js", "ts", "jsx", "tsx"):
            self._analyze_javascript(filename, added_lines)
        elif ext in ("java",):
            self._analyze_generic(filename, added_lines)
        elif ext in ("go", "rs"):
            self._analyze_generic(filename, added_lines)
        else:
            self._analyze_generic(filename, added_lines)

        self._analyze_common(filename, added_lines)

    def _add_comment(self, file: str, line: int, severity: str,
                     category: str, title: str, description: str,
                     suggestion: str):
        self.comments.append(ReviewComment(
            file=file, line=line, severity=severity,
            category=category, title=title,
            description=description, suggestion=suggestion,
        ))

    # ── Language-specific checks ──────────────────────────────

    def _analyze_python(self, filename: str, lines: list):
        for idx, code, lineno in lines:
            stripped = code.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if "except:" in stripped and "Exception" not in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Error Handling",
                    "Bare except clause",
                    "A bare `except:` catches all exceptions including "
                    "KeyboardInterrupt and SystemExit.",
                    "Use `except Exception:` to avoid silencing critical "
                    "interrupts.")

            if "import *" in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Code Quality",
                    "Wildcard import",
                    "`import *` pollutes the namespace and makes it "
                    "unclear where names come from.",
                    "Import only the specific names you need.")

            if "eval(" in stripped or "exec(" in stripped:
                self._add_comment(filename, lineno, SEVERITY_CRITICAL,
                    "Security",
                    "Dangerous function call",
                    "`eval()` / `exec()` can execute arbitrary code and "
                    "is a security risk.",
                    "Avoid dynamic code execution. Use safer alternatives "
                    "like `ast.literal_eval()`.")

            if st := self._re_match(r"open\([^)]+\)\s*$", stripped):
                if "encoding=" not in stripped and "rb" not in stripped \
                        and "wb" not in stripped:
                    self._add_comment(filename, lineno, SEVERITY_INFO,
                        "Best Practice",
                        "Missing file encoding",
                        "Opening a text file without specifying encoding "
                        "can cause cross-platform issues.",
                        "Add `encoding='utf-8'` to the `open()` call.")

            if "==" in stripped and "None" in stripped:
                if "is None" not in stripped:
                    self._add_comment(filename, lineno, SEVERITY_INFO,
                        "Best Practice",
                        "None comparison style",
                        "Use `is None` instead of `== None` for identity "
                        "comparison.",
                        "Change `== None` to `is None`.")

            if "db.execute" in stripped.lower() or "cursor.execute" in stripped.lower():
                m = re.search(r"execute\(\s*[f\"']", stripped)
                if m and "%" not in stripped:
                    pass
                m2 = re.search(r"execute\(\s*[\"'][^\"']*%", stripped)
                if m2 or re.search(r"execute\(\s*f[\"']", stripped):
                    self._add_comment(filename, lineno, SEVERITY_CRITICAL,
                        "Security",
                        "Possible SQL injection",
                        "String formatting in SQL queries can lead to "
                        "SQL injection.",
                        "Use parameterized queries "
                        "(e.g. `cursor.execute('SELECT * FROM t WHERE id=?', (val,))`)")

        if len(lines) > 5:
            self.strengths.append(
                f"{filename}: {len(lines)} line(s) of Python code reviewed")

    def _analyze_javascript(self, filename: str, lines: list):
        for idx, code, lineno in lines:
            stripped = code.strip()
            if not stripped or stripped.startswith(("//", "/*", "*")):
                continue

            if "== " in stripped and "!==" not in stripped \
                    and "===" not in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Best Practice",
                    "Loose equality operator",
                    "`==` performs type coercion which can lead to "
                    "unexpected bugs.",
                    "Use `===` (strict equality) instead of `==`.")

            if "var " in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Code Quality",
                    "Use of 'var'",
                    "`var` has function scoping and can cause subtle bugs.",
                    "Use `const` or `let` instead of `var`.")

            if "innerHTML" in stripped and "=" in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Security",
                    "Potential XSS via innerHTML",
                    "Setting `innerHTML` can introduce cross-site scripting "
                    "vulnerabilities if content is user-controlled.",
                    "Use `textContent` or sanitize the input before "
                    "assigning to `innerHTML`.")

            if "console.log(" in stripped:
                self._add_comment(filename, lineno, SEVERITY_INFO,
                    "Code Quality",
                    "Console log left in code",
                    "Stray `console.log()` call detected in production code.",
                    "Remove or replace with a proper logging framework.")

            if "JSON.parse(" in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Error Handling",
                    "Unwrapped JSON.parse",
                    "`JSON.parse()` throws on malformed input; "
                    "an unhandled exception can crash the app.",
                    "Wrap in `try/catch` or use a safe parsing helper.")

    def _analyze_generic(self, filename: str, lines: list):
        for idx, code, lineno in lines:
            stripped = code.strip()
            if not stripped:
                continue
            if "TODO" in stripped.upper():
                self._add_comment(filename, lineno, SEVERITY_INFO,
                    "Code Quality",
                    "TODO comment left in code",
                    "A TODO or FIXME marker was found.",
                    "Address the TODO before merging, or link to a "
                    "tracking issue.")

            if "FIXME" in stripped.upper():
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Code Quality",
                    "FIXME marker",
                    "A FIXME marker indicates a known bug or issue.",
                    "Fix the issue before merging.")

            if "debugger" in stripped or "DEBUG" in stripped:
                self._add_comment(filename, lineno, SEVERITY_WARNING,
                    "Code Quality",
                    "Debug statement left in code",
                    "A debugger statement or debug flag was found.",
                    "Remove debug statements before merging.")

    def _analyze_common(self, filename: str, lines: list):
        for idx, code, lineno in lines:
            stripped = code.strip()

            if not stripped or stripped.startswith(("#", "//", "/*")):
                continue

            if re.search(
                r"(?i)(password|secret|api_key|token|credential)\s*[:=]\s*['\"]",
                stripped
            ):
                self._add_comment(filename, lineno, SEVERITY_CRITICAL,
                    "Security",
                    "Hardcoded secret detected",
                    "A credential or secret appears to be hardcoded.",
                    "Use environment variables or a secrets manager "
                    "(e.g. `os.getenv()`) instead.")

            if len(stripped) > 200:
                self._add_comment(filename, lineno, SEVERITY_INFO,
                    "Code Quality",
                    "Very long line",
                    f"Line is {len(stripped)} characters long.",
                    "Break the line into multiple lines for readability.")

            if re.search(r"(?i)(hack|workaround|ugly|kludge)", stripped) \
                    and not stripped.startswith(("#", "//")):
                self._add_comment(filename, lineno, SEVERITY_INFO,
                    "Code Quality",
                    "Potentially fragile code",
                    "The code contains language suggesting it's a "
                    "workaround or hack.",
                    "Consider refactoring to a cleaner solution.")

    @staticmethod
    def _re_match(pattern: str, text: str) -> Optional[re.Match]:
        return re.search(pattern, text)


def analyze_pr(pull_request) -> ReviewReport:
    analyzer = CodeAnalyzer()
    return analyzer.analyze(pull_request.files)
