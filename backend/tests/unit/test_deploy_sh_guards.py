"""deploy.sh check_profile_drift (HRP-499 / HRP-1027).

Runs the real shell functions against a stub ``dc``: a running container
behind a parked profile (external-db) must still stop the deploy, but point
at the runbook cleanup instead of advising to enable the profile; any other
drifted profile keeps the original advice.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parents[3] / "deploy" / "deploy.sh"

if not DEPLOY_SH.exists():  # pragma: no cover - public tree without deploy/
    pytest.skip("deploy/deploy.sh not in this tree", allow_module_level=True)

_FUNCS = ("profiles_from_env", "parked_services", "check_profile_drift")

# Stub compose: base services always on, profile services by COMPOSE_PROFILES.
_STUB = r"""
log() { echo "$*"; }; warn() { echo "$*"; }; error() { echo "$*"; }
DEPLOY_DIR=/opt/hrpulsar; COMPOSE_FILE=docker-compose.yml; SITE_ID=""
declare -A PROFILE=([marketing]=marketing [slack-listener]=slack-listener [postgres]=external-db [redis]=external-db)
dc() {
    local svc out="backend frontend"
    if [ "$1" = --profile ]; then echo "$out ${!PROFILE[*]}" | tr ' ' '\n'; return; fi
    for svc in "${!PROFILE[@]}"; do
        case ",${COMPOSE_PROFILES:-}," in *",${PROFILE[$svc]},"*) out="$out $svc";; esac
    done
    echo "$out" | tr ' ' '\n'
}
containers_for_service() { case " $RUNNING " in *" $1 "*) echo id-$1;; esac; }
"""


def _source() -> str:
    text = DEPLOY_SH.read_text()
    parked = re.search(r"^PARKED_PROFILES=.*$", text, re.M)
    assert parked
    parts = [parked.group(0)]
    for name in _FUNCS:
        m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
        assert m, name
        parts.append(m.group(0))
    return "\n".join(parts)


def _run(running: str, profiles: str = "") -> subprocess.CompletedProcess[str]:
    script = f"{_STUB}\n{_source()}\nRUNNING='{running}'\nunset COMPOSE_PROFILES\ncheck_profile_drift"
    env = {"PATH": "/usr/bin:/bin"}
    if profiles:
        script = script.replace(
            "unset COMPOSE_PROFILES", f"export COMPOSE_PROFILES={profiles}"
        )
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env
    )


def test_no_drift_passes() -> None:
    assert _run("backend frontend").returncode == 0


def test_parked_external_db_stops_with_runbook_advice() -> None:
    r = _run("backend postgres redis")
    assert r.returncode == 1
    assert "RU_SITE_ANSIBLE_GUIDE.md" in r.stdout
    assert "Do NOT add the profile" in r.stdout
    assert "Add the missing profile" not in r.stdout
    assert "COMPOSE_PROFILES=marketing" not in r.stdout


def test_other_profiles_keep_original_advice() -> None:
    r = _run("backend marketing slack-listener")
    assert r.returncode == 1
    mismatch = next(
        line for line in r.stdout.splitlines() if "COMPOSE_PROFILES mismatch" in line
    )
    assert "marketing" in mismatch and "slack-listener" in mismatch
    assert "Add the missing profile(s)" in r.stdout
    assert "RU_SITE_ANSIBLE_GUIDE" not in r.stdout


def test_mixed_drift_reports_both_and_never_advises_external_db() -> None:
    r = _run("postgres marketing")
    assert r.returncode == 1
    assert "RU_SITE_ANSIBLE_GUIDE.md" in r.stdout
    mismatch = next(
        line for line in r.stdout.splitlines() if "COMPOSE_PROFILES mismatch" in line
    )
    assert "marketing" in mismatch and "postgres" not in mismatch


def test_pipeline_profiles_parked_still_runbook() -> None:
    r = _run("redis", profiles="slack-listener")
    assert r.returncode == 1
    assert "RU_SITE_ANSIBLE_GUIDE.md" in r.stdout
    assert "fleet manifest" not in r.stdout


# --- check_slack_env (HRP-651) -------------------------------------------


def _slack_env(tmp_path: Path, env: str, listener_on: bool = True) -> str:
    text = DEPLOY_SH.read_text()
    m = re.search(r"^check_slack_env\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert m
    (tmp_path / ".env").write_text(env)
    script = (
        'warn() { echo "$*"; }; DEPLOY_DIR=/opt/hrpulsar\n'
        f"profile_service_active() {{ {'true' if listener_on else 'false'}; }}\n"
        f"{m.group(0)}\ncheck_slack_env"
    )
    r = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert r.returncode == 0, "a warning, never a blocked deploy"
    return r.stdout


def test_slack_env_warns_on_missing_tokens(tmp_path: Path) -> None:
    out = _slack_env(tmp_path, "COMPOSE_PROFILES=slack-listener\nSLACK_BOT_TOKEN=\n")
    assert "SLACK_BOT_TOKEN SLACK_APP_TOKEN SLACK_LEADS_CHANNEL" in out


def test_slack_env_names_only_the_missing_one(tmp_path: Path) -> None:
    out = _slack_env(
        tmp_path,
        'SLACK_BOT_TOKEN=xoxb-1\nSLACK_APP_TOKEN="xapp-1"\n# SLACK_LEADS_CHANNEL=C1\n',
    )
    assert "but SLACK_LEADS_CHANNEL is not set" in out


def test_slack_env_quiet_when_complete_or_listener_off(tmp_path: Path) -> None:
    full = "SLACK_BOT_TOKEN=xoxb-1\nSLACK_APP_TOKEN=xapp-1\nSLACK_LEADS_CHANNEL=C0B6\n"
    assert _slack_env(tmp_path, full) == ""
    exported = "".join(f"export {line}\n" for line in full.splitlines())
    assert _slack_env(tmp_path, exported) == ""
    assert _slack_env(tmp_path, "", listener_on=False) == ""


# --- prune_old_images ----------------------------------------------------


def test_prune_keeps_three_newest_per_app_repo_only(tmp_path: Path) -> None:
    """Old app images go, newest three per repo stay, third-party untouched;
    untagged leftovers of a re-pulled ``:latest`` go too."""
    text = DEPLOY_SH.read_text()
    m = re.search(r"^prune_old_images\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert m
    # ``docker images <repo>`` lists newest first; b2 carries two tags.
    script = r"""
log() { :; }
dc() { printf '%s\n' reg:5000/hrp/backend:2.5.3 reg:5000/hrp/backend:2.5.3 \
    reg:5000/hrp/marketing:latest postgres:17.6; }
docker() {
    case "$1" in
        images) case "$2" in
            reg:5000/hrp/backend) printf '%s\n' b1 b2 b2 b3 b4 b5;;
            reg:5000/hrp/marketing) printf '%s\n' m1 m2;;
            *) echo "unexpected repo $2" >&2; exit 9;;
        esac;;
        rmi|image) echo "$*" >> "$OUT";;
    esac
}
""" + m.group(0) + "prune_old_images"
    out = tmp_path / "rmi.log"
    r = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "OUT": str(out)},
    )
    assert r.returncode == 0, r.stderr
    assert out.read_text().splitlines() == ["rmi b4 b5", "image prune -f"]
