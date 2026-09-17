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
  6. Copy the job-finder / resume-editor skill specs into the profile.
  7. Seed resume-library/resume.md from the example template if missing.
  8. Create .env from .env.example if missing, with PROJECT_ROOT set.
  9. Initialize the database if it doesn't exist yet (never re-inits one
     that already has data).
  10. Create the daily job-finder cron job if it doesn't already exist,
      paused and gated by live_mode (off by default).

Never touches: resume-library/resume.md content (if it already exists),
config/*.md content, or any existing job/run data.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILE_NAME = "job-hunter"
CRON_JOB_NAME = "Job Hunter Daily Search"
CRON_SCHEDULE = "0 8 * * *"
CRON_PROMPT = (
    "Autonomous live-mode run. Do NOT source .env: it can contain values that "
    "are not shell-safe. Read ONLY PROJECT_ROOT from the local .env with a "
    "safe parser, then cd into it. If it is absent or inaccessible, stop and "
    "report that configuration error. Never use a profile directory or a "
    "machine-specific path. First run: python scripts/db.py get-setting --key "
    "live_mode. If its value is not exactly on, exit silently without "
    "changing anything. Live mode runs one full research pass per role "
    "default listed in config/search-config.md -- for each, start a run with "
    "python scripts/db.py start-run using that role plus the seniority/"
    "location defaults, mark it researching, load the job-finder skill, log "
    "matches, then mark-jobs-found (or mark-run-rejected if nothing "
    "qualified), before moving to the next role default. Do not tailor "
    "resumes or mark any run presented in this job, that is a separate "
    "stage. On an actual failure, mark only that run failed with a clear "
    "reason via mark-run-failed. Return a concise local summary covering "
    "both roles."
)
CRON_PAUSED_REASON = "shipped paused; enable by setting live_mode=on via scripts/db.py set-setting"


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
    dst.write_text(src.read_text())
    say("Wrote profile SOUL.md (persona / scope)")


def ensure_skills(profile_dir):
    for name in ("job-finder", "resume-editor"):
        src = ROOT / "hermes-skills" / name / "SKILL.md"
        dst_dir = profile_dir / "skills" / name
        dst_dir.mkdir(parents=True, exist_ok=True)
        (dst_dir / "SKILL.md").write_text(src.read_text())
    say("Synced job-finder and resume-editor skills into the profile")


def ensure_resume_placeholder():
    resume = ROOT / "resume-library" / "resume.md"
    example = ROOT / "resume-library" / "resume.example.md"
    if not resume.exists() and example.exists():
        resume.write_text(example.read_text())
        say("Seeded resume-library/resume.md from the example template -- replace it with your real CV")
    else:
        say("resume-library/resume.md already exists -- left as-is")


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
    db_path = ROOT / "data" / "job-hunter.db"
    if db_path.exists():
        say("Database already exists -- left as-is (not re-initialized)")
        return
    say("Initializing database...")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "db.py"), "init"])
    if result.returncode != 0:
        raise RuntimeError("Database initialization failed")
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "db.py"),
        "set-setting", "--key", "live_mode", "--value", "off",
    ])
    say("Database initialized, live_mode=off")


def ensure_cron():
    code, out, err = run_hermes(["-p", PROFILE_NAME, "cron", "list", "--all"])
    if code == 0 and CRON_JOB_NAME in (out or ""):
        say(f"Cron job '{CRON_JOB_NAME}' already exists -- left as-is")
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
    say("Cron job created, paused. It will not run until you set live_mode=on.")


def main():
    say("Job Hunter -- Hermes profile setup")
    require_hermes()
    profile_dir = ensure_profile()
    hermes_home = profile_dir.parent.parent
    ensure_config_yaml(profile_dir, hermes_home)
    ensure_soul(profile_dir)
    ensure_skills(profile_dir)
    ensure_resume_placeholder()
    ensure_env_file()
    ensure_database()
    ensure_cron()

    print()
    say("Setup complete. Next steps:")
    print(f"  1. Replace resume-library/resume.md with your real CV.")
    print(f"  2. Edit config/target-companies.md and config/search-config.md.")
    print(f"  3. Chat with it: hermes -p {PROFILE_NAME} chat")
    print(f"     (try /model first if you see an inference error -- pick any")
    print(f"      available model, free tiers included)")
    print(f"  4. Try: \"find jobs\" to test a manual run before enabling live_mode.")
    print(f"  5. Dashboard: python scripts/dashboard-server.py, then open")
    print(f"     http://127.0.0.1:5301/")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        warn(str(e))
        sys.exit(1)
