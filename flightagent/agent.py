"""Turn an owner's free-text request into a proposed change for review (pull request).

Run by .github/workflows/agent.yml. Sends the request plus the editable project
files to Gemini (free tier), applies the find/replace edits it returns to the
working tree, and checks them (compile, unit tests, config, dashboard JS syntax).
One retry feeds failures back to the model. The workflow then opens a pull
request; nothing reaches main until the owner merges it.

Never edits .github/, docs/data/ or this file.

    python -m flightagent.agent --prompt-file prompt.txt --out agent_result.json

Env: GEMINI_API_KEY (required), GEMINI_MODEL (optional).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITABLE = ["config.yaml", "config-bhaarat.yaml", "docs/jay/index.html", "docs/bhaarat/index.html", "README.md"]
EDITABLE_GLOBS = ["flightagent/*.py", "flightagent/providers/*.py", "tests/*.py"]
PROTECTED = {"flightagent/agent.py"}
MODELS = ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]  # free-tier models, first to answer wins
API = "https://generativelanguage.googleapis.com/v1beta"
REQUEST_TIMEOUT = 120  # seconds per model request
DEADLINE = 14 * 60     # give up (and report) well inside the workflow's 20-minute job limit
_START = time.monotonic()


def _left() -> float:
    return DEADLINE - (time.monotonic() - _START)


def _log(msg: str) -> None:
    print(f"[agent {int(time.monotonic() - _START):4d}s] {msg}", file=sys.stderr, flush=True)

SYSTEM = """You maintain a small flight-price monitor. Python (flightagent/) searches Google Flights
and Skiplagged hourly in GitHub Actions and writes docs/<person>/data/latest.json. There are two
people: jay (config.yaml, docs/jay/index.html) and bhaarat (config-bhaarat.yaml,
docs/bhaarat/index.html). The two index.html files are the same static dashboard (vanilla JS, no
build step); keep them identical: when you change one, make the same edit to the other.
config.yaml holds the searches, filters, and `tracked:` (specific flights priced per seller).
Your change is opened as a pull request.

Make the smallest change that does what the owner asks. Rules:
- Only edit the files provided. Prefer config.yaml when a setting already exists for the request.
- Keep the code style of the file you edit. Keep the dashboard clean and minimal.
- In the dashboard, build DOM with the existing $() helper and textContent; never use innerHTML
  with data, and pass any URL through safeUrl().
- Don't add dependencies, network services, secrets, or tracking.
- If the request is unclear, unsafe, or impossible within these files, return no edits and explain.

Respond with JSON only:
{"title": "<short pull request title>",
 "summary": "<one or two sentences for the owner, plain language>",
 "edits": [{"path": "<file>", "find": "<exact text currently in the file, unique>", "replace": "<new text>"}]}
"find" must match the current file exactly once, including whitespace; include enough
surrounding lines to be unique. To create a new file under flightagent/ or tests/, use "find": "".
"""


def editable_files() -> list[str]:
    paths = set(EDITABLE)
    for g in EDITABLE_GLOBS:
        paths |= {str(p.relative_to(ROOT)) for p in ROOT.glob(g)}
    return sorted(p for p in paths - PROTECTED if (ROOT / p).exists())


def allowed_path(path: str) -> bool:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or path in PROTECTED:
        return False
    return path in EDITABLE or any(p.match(g) for g in EDITABLE_GLOBS)


def build_prompt(request: str, feedback: str | None) -> str:
    parts = [f"Today is {date.today().isoformat()}.\n\nOWNER REQUEST:\n{request.strip()}\n"]
    if feedback:
        parts.append(f"\nYOUR PREVIOUS ATTEMPT FAILED CHECKS. Fix it:\n{feedback}\n")
    parts.append("\nPROJECT FILES:\n")
    for path in editable_files():
        parts.append(f"\n===== {path} =====\n{(ROOT / path).read_text()}\n")
    return "".join(parts)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")  # tolerate prose around the object
        return json.loads(text[start:end + 1])


def _generate_content(client, key: str, model: str, prompt: str) -> str:
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
    }
    r = client.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=min(REQUEST_TIMEOUT, max(5, _left())))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _interactions(client, key: str, model: str, prompt: str) -> str:
    """Google's newer API; new models may only be served here."""
    body = {"model": model, "input": prompt, "system_instruction": SYSTEM}
    r = client.post(f"{API}/interactions", headers={"x-goog-api-key": key}, json=body, timeout=min(REQUEST_TIMEOUT, max(5, _left())))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    texts = [c.get("text", "") for st in data.get("steps", []) if st.get("type") == "model_output"
             for c in st.get("content", []) if c.get("type", "text") == "text"]
    text = "".join(texts) or data.get("output_text", "")
    if not text:
        raise RuntimeError(f"no text in response (status {data.get('status')})")
    return text


def call_model(prompt: str) -> dict:
    from primp import Client  # imported here so allowed_path() works without dependencies

    key = os.environ["GEMINI_API_KEY"]
    models = [os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL") else MODELS
    client, errors = Client(), []
    # Free-tier capacity comes and goes: on "busy" (503) or rate-limit (429) answers,
    # wait and go round again (about 8 minutes in total) before giving up.
    for wait in (0, 30, 60, 120, 240):
        if wait:
            if _left() < wait + 30:
                errors.append(f"stopped retrying: {DEADLINE // 60}-minute time limit reached")
                break
            _log(f"models busy; waiting {wait}s")
            time.sleep(wait)
        busy = False
        for model in models:
            for api in (_generate_content, _interactions):
                if _left() < 10:
                    raise RuntimeError("no model answered in time:\n" + "\n".join(errors[-6:]))
                _log(f"asking {model} via {api.__name__.strip('_')}")
                try:
                    reply = _parse_json(api(client, key, model, prompt))
                    _log("got a reply")
                    return reply
                except Exception as e:  # report every attempt; the last one alone hides the real cause
                    msg = str(e)
                    _log(f"failed: {type(e).__name__}: {msg[:150]}")
                    errors.append(f"{model} via {api.__name__.strip('_')}: {type(e).__name__}: {msg[:200]}")
                    if msg.startswith(("HTTP 503", "HTTP 429")):
                        busy = True
                        break  # the other API serves the same capacity; move to the next model
        if not busy:
            break  # a real error (bad key, bad request), so retrying won't help
    raise RuntimeError("no model answered:\n" + "\n".join(errors[-6:]))


def apply_edits(edits: list[dict]) -> list[str]:
    """Apply all edits or none; returns changed paths. Raises ValueError with a model-readable reason."""
    staged: dict[str, str] = {}
    for e in edits:
        path, find, replace = e.get("path", ""), e.get("find", ""), e.get("replace", "")
        if not allowed_path(path):
            raise ValueError(f"{path}: not an editable file")
        f = ROOT / path
        cur = staged.get(path, f.read_text() if f.exists() else None)
        if find == "":
            if cur is not None:
                raise ValueError(f"{path}: empty 'find' is only for creating new files")
            staged[path] = replace
            continue
        if cur is None:
            raise ValueError(f"{path}: file does not exist")
        n = cur.count(find)
        if n != 1:
            raise ValueError(f"{path}: 'find' text matched {n} times (must be exactly 1): {find[:120]!r}")
        staged[path] = cur.replace(find, replace)
    for path, text in staged.items():
        (ROOT / path).write_text(text)
    return sorted(staged)


def _run(cmd: list[str]) -> str | None:
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}  # checked code never sees the key
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    return None if p.returncode == 0 else (p.stdout + p.stderr)[-3000:]


def check(changed: list[str]) -> str | None:
    import yaml

    errors = []
    try:
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
        for s in cfg["searches"]:
            assert s["origin"] and s["destination"], "each search needs origin and destination"
            date.fromisoformat(str(s["date"]))
    except Exception as e:
        errors.append(f"config.yaml invalid: {type(e).__name__}: {e}")
    py = [p for p in changed if p.endswith(".py")]
    if py and (err := _run([sys.executable, "-m", "py_compile", *py])):
        errors.append(f"python compile failed:\n{err}")
    if err := _run([sys.executable, "-m", "unittest", "discover", "-s", "tests"]):
        errors.append(f"unit tests failed:\n{err}")
    for page in [p for p in changed if p.endswith("index.html")]:
        html = (ROOT / page).read_text()
        scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
        if not scripts or "</html>" not in html:
            errors.append(f"{page}: missing <script> or </html>")
        elif subprocess.run(["which", "node"], capture_output=True).returncode == 0:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as t:
                t.write("\n".join(scripts))
            if err := _run(["node", "--check", t.name]):
                errors.append(f"dashboard JavaScript syntax error:\n{err}")
    return "\n\n".join(errors) or None


def revert(paths: list[str]) -> None:
    tracked = [p for p in paths if subprocess.run(["git", "ls-files", "--error-unmatch", p], cwd=ROOT, capture_output=True).returncode == 0]
    if tracked:
        subprocess.run(["git", "checkout", "--", *tracked], cwd=ROOT, check=True)
    for p in set(paths) - set(tracked):
        (ROOT / p).unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", default="agent_result.json")
    args = ap.parse_args()
    request = Path(args.prompt_file).read_text()
    result = {"status": "failed", "title": "", "summary": "", "changed": [], "error": ""}
    feedback = None
    for _ in range(2):
        if _left() < 60:
            result["error"] = (result["error"] + "\n" if result["error"] else "") + "ran out of time"
            break
        try:
            reply = call_model(build_prompt(request, feedback))
        except Exception as e:
            result["error"] = f"model call failed: {e}"
            break
        result["title"] = str(reply.get("title", ""))[:120]
        result["summary"] = str(reply.get("summary", ""))[:1000]
        edits = reply.get("edits") or []
        if not edits:
            result["status"] = "no_change"
            break
        try:
            changed = apply_edits(edits)
        except (ValueError, OSError) as e:
            feedback = result["error"] = str(e)
            continue
        _log(f"checking edits to {', '.join(changed)}")
        problems = check(changed)
        if problems is None:
            result.update(status="ok", changed=changed, error="")
            break
        revert(changed)
        feedback = problems
        result["error"] = problems[:2000]
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(result["status"], result["title"], result["error"][:500], sep="\n")


if __name__ == "__main__":
    main()
