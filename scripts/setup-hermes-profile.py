#!/usr/bin/env python3
"""One-time setup: creates (or repairs) the `job-hunter` Hermes profile and
points it at this project. Run via install.bat (Windows) or install.command
(macOS) -- both just bootstrap Python then call this script. Safe to re-run:
every step checks current state first and only fills in what's missing, so
running it again on an already-configured machine changes nothing.

What it does, in order:
  1. Confirm the `hermes` CLI is on PATH (stop with clear guidance if not).
  2. Create the `job-hunter` profile if it doesn't exist yet.
  3. Point its terminal.cwd at this project folder.
  4. Best-effort copy a working model/provider from whatever profile is
     currently active, so chat works without an extra manual step -- but
     never overwrites a model already configured on job-hunter.
  5. Write this project's SOUL.md (persona/scope) into the profile.
  6. Copy the onboarding / job-finder / resume-editor / resume-pdf-designer
     skills into the profile.
  7. Check this machine can read and make PDFs (resumes are PDF only).
  8. Create .env from .env.example if missing, with PROJECT_ROOT set.
  9. Create the database if it doesn't exist yet; if it does, run the
     non-destructive migration (never re-inits one that already has data).
  10. Create the daily job-finder cron job if it doesn't already exist, paused
      (turn it on with `hermes cron resume`), and keep an existing one's prompt
      in sync with this file.

The first chat after install runs the onboarding skill (resume PDF, roles,
companies) -- this script deliberately does not seed any resume or config.

Never touches: resume-library/resume.pdf, config/*.md content, or any
existing job/run data.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_NAME = "job-hunter"
CRON_JOB_NAME = "Job Hunter Daily Search"
CRON_SCHEDULE = "0 8 * * *"
CRON_PROMPT = (
    "Daily Job Hunter search. Do NOT source .env: it can contain values that "
    "are not shell-safe. Read ONLY PROJECT_ROOT from the local .env with a "
    "safe parser, then cd into it. If it is absent or inaccessible, stop and "
    "report that configuration error. Never use a profile directory or a "
    "machine-specific path. First run: python scripts/check-setup.py. If "
    "configured is not true, stop and report that setup is unfinished; do "
    "nothing else. Otherwise load the job-finder skill and run one full "
    "research pass per Role line in config/search-config.md, one role at a "
    "time, each taken to completion before the next. Only jobs posted within "
    "the freshness window are kept, and only from company career pages, never "
    "job boards. Do not tailor resumes or mark any run presented in this job; "
    "that is a separate stage. On an actual failure, mark only that run failed "
    "with a clear reason via mark-run-failed. Return a concise local summary "
    "covering every role."
)
CRON_PAUSED_REASON = "created paused; turn on with: hermes -p job-hunter cron resume <job id>"


def say(msg):
    print(f"==> {msg}")


def warn(msg):
    print(f"!!  {msg}")


def run_hermes(args, check=False):
    """Run a hermes CLI subcommand, returning (returncode, stdout, stderr).
    Never raises on a non-zero exit -- callers decide what that means."""
    try:
        result = subprocess.run(
            ["hermes", *args], capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return 127, "", "hermes not found"
    except subprocess.TimeoutExpired:
        return 124, "", "hermes command timed out"
    if check and result.returncode != 0:
        raise RuntimeError(f"hermes {' '.join(args)} failed: {result.stderr}")
    return result.returncode, result.stdout, result.stderr


def require_hermes():
    if shutil.which("hermes") is None:
        warn("Hermes AI ('hermes' command) was not found on PATH.")
        warn("Install it from https://nousresearch.com, then re-run this installer.")
        sys.exit(1)


def profile_dir_for(name):
    """Returns the profile's directory Path by asking hermes itself (so we
    never have to guess the per-OS HERMES_HOME location), or None if the
    profile doesn't exist."""
    code, out, _ = run_hermes(["profile", "show", name])
    if code != 0:
        return None
    for line in out.splitlines():
        if line.strip().startswith("Path:"):
            return Path(line.split("Path:", 1)[1].strip())
    return None


def ensure_profile():
    existing = profile_dir_for(PROFILE_NAME)
    if existing:
        say(f"Profile '{PROFILE_NAME}' already exists at {existing}")
        return existing
    say(f"Creating Hermes profile '{PROFILE_NAME}'...")
    description = (
        "Job Hunter: finds real job listings on target companies' own career "
        "pages, matches them against the user's CV, and tailors a resume per "
        "match. Read-only dashboard, no apply/send stage."
    )
    code, out, err = run_hermes([
        "profile", "create", PROFILE_NAME, "--no-skills",
        "--description", description,
    ])
    if code != 0:
        raise RuntimeError(f"Could not create profile: {err or out}")
    profile_dir = profile_dir_for(PROFILE_NAME)
    if not profile_dir:
        raise RuntimeError("Profile was created but its directory could not be located.")
    say(f"Profile created at {profile_dir}")
    return profile_dir


def _find_top_level_block(text, key):
    """Return the raw lines of a top-level `key:` block from simple,
    Hermes-generated YAML (2-space indented children, no anchors/flow
    style) -- a hand-rolled scan so this script has no YAML dependency."""
    lines = text.splitlines()
    out = []
    in_block = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            if in_block:
                out.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            if line.strip() == f"{key}:" or line.strip().startswith(f"{key}:"):
                in_block = True
                out.append(line)
                continue
            if in_block:
                break
            continue
        if in_block:
            out.append(line)
    return out if out else None


def find_a_working_model_block(hermes_home):
    """Best-effort: find a `model:` block already configured somewhere else
    on this machine, to copy into the fresh job-hunter profile so chat works
    without an extra manual step. Tries the currently active profile's own
    config.yaml, then the global config.yaml. Returns a list of raw lines,
    or None if nothing usable was found -- in which case the caller leaves
    model selection to the user (via `hermes -p job-hunter model`)."""
    active_file = hermes_home / "active_profile"
    candidates = []
    try:
        active_name = active_file.read_text().strip()
        if active_name and active_name != PROFILE_NAME:
            candidates.append(hermes_home / "profiles" / active_name / "config.yaml")
    except Exception:
        pass
    candidates.append(hermes_home / "config.yaml")

    for path in candidates:
        try:
            text = path.read_text()
        except Exception:
            continue
        block = _find_top_level_block(text, "model")
        if block:
            return block
    return None


def ensure_config_yaml(profile_dir, hermes_home):
    config_path = profile_dir / "config.yaml"
    existing = config_path.read_text() if config_path.exists() else ""

    # 1. terminal.cwd -- always kept in sync with this project's real location.
    lines = existing.splitlines()
    out, in_terminal, done = [], False, False
    for raw in lines:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            if in_terminal and not done:
                out.append(f"  cwd: {ROOT}")
                done = True
            in_terminal = stripped.startswith("terminal:")
            out.append(raw)
            continue
        if in_terminal and stripped.startswith("cwd:"):
            out.append(f"  cwd: {ROOT}")
            done = True
            continue
        out.append(raw)
    if in_terminal and not done:
        out.append(f"  cwd: {ROOT}")
        done = True
    if not done:
        out = ["terminal:", f"  cwd: {ROOT}"] + out
    new_text = "\n".join(out)
    if not new_text.endswith("\n"):
        new_text += "\n"
    say("Set terminal.cwd to this project folder")

    # 2. model: -- only if job-hunter doesn't already have one configured.
    if _find_top_level_block(new_text, "model") is None:
        block = find_a_working_model_block(hermes_home)
        if block:
            new_text = new_text.rstrip("\n") + "\n" + "\n".join(block) + "\n"
            say("Copied a model/provider config from an existing profile (best effort)")
        else:
            warn("No existing model/provider config found to copy.")
            warn(f"Run 'hermes -p {PROFILE_NAME} model' to pick one (free tiers included) before chatting.")
    else:
        say("Profile already has a model/provider configured -- left as-is")

    config_path.write_text(new_text)


def ensure_soul(profile_dir):
    src = ROOT / "hermes-skills" / "SOUL.md"
    dst = profile_dir / "SOUL.md"
    shutil.copyfile(src, dst)
    say("Wrote profile SOUL.md (persona / scope)")


SKILL_NAMES = ("onboarding", "job-finder", "resume-editor", "resume-pdf-designer")


def ensure_skills(profile_dir):
    for name in SKILL_NAMES:
        src = ROOT / "hermes-skills" / name / "SKILL.md"
        dst_dir = profile_dir / "skills" / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst_dir / "SKILL.md")
    say(f"Synced {', '.join(SKILL_NAMES)} skills into the profile")


def check_pdf_tooling():
    """Resumes are PDF only, so this machine needs a PDF reader and a PDF maker.
    Only warns -- the first chat's onboarding repeats the hint if it matters."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pdf-tools.py"), "check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        warn("Could not check PDF tooling.")
        return
    if report.get("ok"):
        say(f"PDF tooling ready (read: {', '.join(report['extract'])}; make: {', '.join(report['render'])})")
    else:
        for hint in report.get("hints", []):
            warn(hint)


def ensure_env_file():
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"
    if env_path.exists():
        say(".env already exists -- left as-is")
        return
    text = example_path.read_text() if example_path.exists() else ""
    lines = text.splitlines()
    out, replaced = [], False
    for line in lines:
        if line.strip().startswith("PROJECT_ROOT=") and not line.strip().startswith("#"):
            out.append(f"PROJECT_ROOT={ROOT}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, f"PROJECT_ROOT={ROOT}")
    env_path.write_text("\n".join(out) + "\n")
    say(f".env created with PROJECT_ROOT={ROOT}")


def ensure_database():
    db_script = str(ROOT / "scripts" / "db.py")
    db_path = ROOT / "data" / "job-hunter.db"
    if db_path.exists():
        result = subprocess.run([sys.executable, db_script, "migrate"])
        if result.returncode != 0:
            raise RuntimeError("Database migration failed")
        say("Database already exists -- migrated in place, no data removed")
        return
    say("Initializing database...")
    result = subprocess.run([sys.executable, db_script, "init"])
    if result.returncode != 0:
        raise RuntimeError("Database initialization failed")
    say("Database initialized")


def existing_cron_job(profile_dir):
    """The managed cron job (a dict from the profile's own jobs.json), or None."""
    try:
        data = json.loads((profile_dir / "cron" / "jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    for job in data.get("jobs", []):
        if job.get("name") == CRON_JOB_NAME:
            return job
    return None


def ensure_cron(profile_dir):
    existing = existing_cron_job(profile_dir)
    if existing and "live_mode" in (existing.get("paused_reason") or ""):
        # Legacy job from before live_mode was removed. Its stored pause reason
        # can't be edited, so recreate it (still paused). Only ever done while it
        # carries that old reason, so a job the user has since enabled is untouched.
        code, out, err = run_hermes(["-p", PROFILE_NAME, "cron", "remove", existing["id"]])
        if code != 0:
            warn(f"Could not replace the old cron job: {err or out}")
            return
        say("Replaced the old daily-search job (it referenced the removed live_mode)")
        existing = None
    if existing:
        job_id = existing["id"]
        if existing.get("prompt") == CRON_PROMPT:
            say(f"Cron job '{CRON_JOB_NAME}' already exists and is up to date -- left as-is")
            return
        code, out, err = run_hermes(["-p", PROFILE_NAME, "cron", "edit", job_id, "--prompt", CRON_PROMPT])
        if code == 0:
            say(f"Cron job '{CRON_JOB_NAME}' updated to the current instructions (its on/off state is unchanged)")
        else:
            warn(f"Could not update the cron job's instructions: {err or out}")
        return
    say("Creating daily job-finder cron job (paused)...")
    code, out, err = run_hermes([
        "-p", PROFILE_NAME, "cron", "create", CRON_SCHEDULE, CRON_PROMPT,
        "--name", CRON_JOB_NAME,
        "--skill", "job-finder",
        "--workdir", str(ROOT),
        "--deliver", "local",
        "--paused",
        "--paused-reason", CRON_PAUSED_REASON,
    ])
    if code != 0:
        warn(f"Could not create the cron job automatically: {err or out}")
        warn("You can create it later from chat, or re-run this installer.")
        return
    say("Cron job created, paused. Turn it on later with: hermes -p job-hunter cron resume <job id>")


def main():
    say("Job Hunter -- Hermes profile setup")
    require_hermes()
    profile_dir = ensure_profile()
    hermes_home = profile_dir.parent.parent
    ensure_config_yaml(profile_dir, hermes_home)
    ensure_soul(profile_dir)
    ensure_skills(profile_dir)
    check_pdf_tooling()
    ensure_env_file()
    ensure_database()
    ensure_cron(profile_dir)

    print()
    say("Setup complete. Next steps:")
    print(f"  1. Open a chat with the job-hunter profile:")
    print(f"       hermes -p {PROFILE_NAME} chat")
    print(f"     (or pick the job-hunter profile in the Hermes app)")
    print(f"  2. Say hi. The first chat walks you through setup: your resume PDF,")
    print(f"     the roles you want, and your target companies.")
    print(f"  3. If you see an inference error, type /model and pick any available")
    print(f"     model (free tiers included).")
    print(f"  4. The beginner's guide with copy-and-paste prompts is at")
    print(f"     docs/Job-Hunter-User-Guide.pdf")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        warn(str(e))
        sys.exit(1)
