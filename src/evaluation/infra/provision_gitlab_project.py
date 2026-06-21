#!/usr/bin/env python3
"""Runtime GitLab project provisioning helper.

Invoked by the adapters (Hermes / OpenClaw) before a task runs to create a
fresh per-task GitLab project cloned from the project template.
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib import request
from urllib import parse
import subprocess

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

SERVICE_MANAGER_URL = 'http://127.0.0.1:2998'
SERVICE_MANAGER_CONTAINER = 'bench-service-manager'
# src/evaluation/infra/provision_gitlab_project.py -> parents[2] = src/
REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT.parent
CASES_ROOT = PROJECT_ROOT / 'cases'
DEFAULT_PROJECT_TEMPLATE = 'project'
DEFAULT_GITLAB_TEMPLATE_PROJECT = 'agent-sandbox-template'


def wait_api(timeout=120):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = subprocess.run(
                [
                    'docker',
                    'exec',
                    SERVICE_MANAGER_CONTAINER,
                    'wget',
                    '-qO-',
                    'http://127.0.0.1:2998/api/status',
                ],
                text=True,
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return
        except Exception:
            pass
        try:
            with request.urlopen(f'{SERVICE_MANAGER_URL}/api/status', timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError('service-manager API did not become ready in time')


def iter_case_dirs():
    return sorted(path.parent for path in CASES_ROOT.glob('*/*/case.yaml'))


def load_case_meta(task_id, task_dir_arg=None):
    if task_dir_arg:
        task_dir = Path(task_dir_arg)
        if not task_dir.exists():
            raise SystemExit(f'case directory not found: {task_dir}')
        meta_path = task_dir / 'case.yaml'
        if not meta_path.exists():
            raise SystemExit(f'case.yaml not found under: {task_dir}')
        meta = load_structured_file(meta_path)
        candidate_id = str(meta.get('case_id') or task_dir.name).strip()
        if candidate_id != task_id:
            raise SystemExit(f'case id mismatch: requested {task_id}, found {candidate_id} in {task_dir}')
        meta.setdefault('id', candidate_id)
        if not meta.get('project_template'):
            meta['project_template'] = (meta.get('runtime') or {}).get('project_template', DEFAULT_PROJECT_TEMPLATE)
        meta['_case_dir'] = str(task_dir.resolve())
        return meta

    for case_dir in iter_case_dirs():
        meta_path = case_dir / 'case.yaml'
        meta = load_structured_file(meta_path)
        candidate_id = str(meta.get('case_id') or case_dir.name).strip()
        if candidate_id == task_id:
            meta.setdefault('id', candidate_id)
            if not meta.get('project_template'):
                meta['project_template'] = (meta.get('runtime') or {}).get('project_template', DEFAULT_PROJECT_TEMPLATE)
            meta['_case_dir'] = str(case_dir.resolve())
            return meta
    raise SystemExit(f'case metadata not found for {task_id}')


def normalize_project_template(value):
    return (value or DEFAULT_PROJECT_TEMPLATE).strip()


def load_structured_file(path):
    text = path.read_text(encoding='utf-8')
    if yaml is not None:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit(f'{path} must contain an object')
    return data


def template_project_name(project_template, context=None):
    if project_template == DEFAULT_PROJECT_TEMPLATE:
        return DEFAULT_GITLAB_TEMPLATE_PROJECT
    return f'{project_template}-template'


def build_project_name(task_id, executor, project_template):
    suffix = datetime.now().strftime('%Y%m%d-%H%M%S')
    return f"{project_template}-run-{task_id.lower()}-{executor}-{suffix}"


def provision_remote_project(project_name, project_template):
    payload = json.dumps({
        'project_name': project_name,
        'project_slug': project_template,
        'template_project': template_project_name(project_template),
    }).encode('utf-8')
    payload_text = payload.decode('utf-8')
    docker_result = subprocess.run(
        [
            'docker',
            'exec',
            SERVICE_MANAGER_CONTAINER,
            'python3',
            '-c',
            (
                "import sys, urllib.request; "
                f"data={payload_text!r}.encode('utf-8'); "
                "req=urllib.request.Request("
                "'http://127.0.0.1:2998/api/gitlab/create-project-from-template',"
                "data=data, headers={'Content-Type':'application/json'}, method='POST'); "
                "print(urllib.request.urlopen(req, timeout=120).read().decode('utf-8'))"
            ),
        ],
        text=True,
        capture_output=True,
        timeout=180,
    )
    if docker_result.returncode == 0 and (docker_result.stdout or "").strip():
        return json.loads(docker_result.stdout.strip())

    req = request.Request(
        f'{SERVICE_MANAGER_URL}/api/gitlab/create-project-from-template',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


def apply_case_overlay(project, meta):
    case_dir = Path(meta.get('_case_dir') or '')
    if not case_dir.exists():
        return {'ok': False, 'reason': 'case directory missing'}

    token = (project.get('token') or project.get('access_token') or ensure_gitlab_token()).strip()
    if token and not project.get('token'):
        project['token'] = token
    repo_url = (project.get('http_url_to_repo') or '').strip()
    if not token or not repo_url:
        return {'ok': False, 'reason': 'missing gitlab token or repo url'}

    overlay_dir = resolve_overlay_dir(case_dir, meta)
    prompt_text = load_prompt_text(case_dir, meta)
    file_map = build_overlay_file_map(case_dir, meta, overlay_dir, prompt_text)
    if not file_map:
        return {'ok': True, 'files': [], 'commit': None}

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        worktree = Path(tmp) / 'repo'
        host_repo_url = host_reachable_gitlab_url(repo_url)
        auth_url = host_repo_url.replace('http://', f'http://oauth2:{token}@', 1)
        run(['git', 'clone', auth_url, str(worktree)])
        run(['git', 'checkout', 'main'], cwd=worktree, check=False)

        written = []
        for rel_path, src in file_map.items():
            dst = worktree / rel_path
            if not is_relative_to(dst.resolve(), worktree.resolve()):
                raise RuntimeError(f'unsafe overlay destination: {rel_path}')
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            written.append(rel_path)

        context_path = worktree / 'CASE_CONTEXT.md'
        context_path.write_text(build_case_context(meta, written), encoding='utf-8')
        written.append('CASE_CONTEXT.md')

        run(['git', 'config', 'user.name', 'Agent Sandbox Case Builder'], cwd=worktree)
        run(['git', 'config', 'user.email', 'agent-sandbox@example.com'], cwd=worktree)
        run(['git', 'add', '.'], cwd=worktree)
        status = run(['git', 'status', '--porcelain'], cwd=worktree)
        if not (status.stdout or '').strip():
            return {'ok': True, 'files': written, 'commit': None}
        run(['git', 'commit', '-m', f"Apply case overlay {meta.get('id') or meta.get('case_id')}"], cwd=worktree)
        run(['git', 'push', 'origin', 'HEAD:main'], cwd=worktree)
        commit = run(['git', 'rev-parse', 'HEAD'], cwd=worktree).stdout.strip()
        return {'ok': True, 'files': written, 'commit': commit, 'overlay_dir': str(overlay_dir) if overlay_dir else None}


def host_reachable_gitlab_url(url):
    parsed = parse.urlsplit(url)
    if parsed.hostname == 'gitlab':
        netloc = '127.0.0.1:8929'
        return parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return url


def ensure_gitlab_token():
    existing = os.environ.get('GITLAB_BENCH_TOKEN') or os.environ.get('BENCH_GITLAB_TOKEN')
    if existing:
        return existing
    expires = (date.today() + timedelta(days=30)).isoformat()
    ruby = (
        'u = User.first || User.find_by_username("root")\n'
        f'pat = PersonalAccessToken.new(user: u, name: "agent-sandbox-overlay-{int(datetime.now().timestamp())}", '
        'scopes: ["api","read_api","read_repository","write_repository"], '
        f'expires_at: Date.parse("{expires}"))\n'
        'raw = SecureRandom.hex(20)\n'
        'pat.set_token(raw)\n'
        'pat.save!\n'
        'puts raw\n'
    )
    result = subprocess.run(
        ['docker', 'exec', 'bench-gitlab', 'gitlab-rails', 'runner', ruby],
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f'failed to create GitLab token: {result.stderr or result.stdout}')
    lines = [line.strip() for line in (result.stdout or '').splitlines() if line.strip()]
    return lines[-1] if lines else ''


def resolve_overlay_dir(case_dir, meta):
    runtime = meta.get('runtime') or {}
    configured = meta.get('repo_overlay') or runtime.get('repo_overlay')
    if configured:
        path = Path(str(configured))
        return path if path.is_absolute() else case_dir / path
    overlay = case_dir / 'overlay'
    return overlay if overlay.exists() else case_dir / 'environment'


def load_prompt_text(case_dir, meta):
    prompt = case_dir / 'prompt.txt'
    if prompt.exists():
        return prompt.read_text(encoding='utf-8')
    rounds = (meta.get('interaction') or {}).get('rounds') or []
    if rounds and isinstance(rounds[0], dict):
        return str(rounds[0].get('payload') or '')
    return ''


def build_overlay_file_map(case_dir, meta, overlay_dir, prompt_text):
    file_map = {}
    artifact_refs = [Path(ref) for ref in meta.get('artifact_refs', []) if Path(ref).exists()]
    prompt_paths = prompt_workspace_paths(prompt_text)
    mapped_artifacts = set()
    if artifact_refs and prompt_paths:
        for index, prompt_path in enumerate(prompt_paths):
            src = artifact_refs[min(index, len(artifact_refs) - 1)]
            rel = prompt_path_to_repo_relpath(prompt_path)
            file_map[rel] = src
            mapped_artifacts.add(src.resolve())

    if overlay_dir and overlay_dir.exists():
        for src in sorted(path for path in overlay_dir.rglob('*') if path.is_file()):
            if src.resolve() in mapped_artifacts:
                continue
            rel = src.relative_to(overlay_dir).as_posix()
            if is_overlay_metadata_file(rel):
                continue
            file_map[rel] = src
    return dict(sorted(file_map.items()))


def is_overlay_metadata_file(rel_path):
    return rel_path in {'README.md'}


def prompt_workspace_paths(text):
    paths = []
    for match in re.findall(r'`([^`]+)`', text or ''):
        value = match.strip()
        if (value.startswith('sandbox/project/') or value.startswith('project/')) and value not in paths:
            paths.append(value)
    return paths


def prompt_path_to_repo_relpath(prompt_path):
    for prefix in ('sandbox/project/', 'project/'):
        if prompt_path.startswith(prefix):
            return prompt_path[len(prefix):]
    return prompt_path.lstrip('/')


def build_case_context(meta, written):
    return (
        '# Workspace Context\n\n'
        f"- Task package: `{meta.get('id') or meta.get('case_id')}`\n"
        '- This repository contains the files needed for the requested workspace task.\n\n'
        '## Files\n\n'
        + ''.join(f"- `{path}`\n" for path in written)
    )


def is_relative_to(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def run(cmd, cwd=None, check=True):
    result = subprocess.run(cmd, text=True, capture_output=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def main():
    if len(sys.argv) < 3:
        raise SystemExit('usage: provision_gitlab_project.py <case-id> <executor> [case-dir]')
    wait_api()
    task_id = sys.argv[1]
    executor = sys.argv[2]
    task_dir_arg = sys.argv[3] if len(sys.argv) >= 4 else None
    meta = load_case_meta(task_id, task_dir_arg)
    project_template = normalize_project_template(meta.get('project_template'))
    project_name = build_project_name(task_id, executor, project_template)
    data = provision_remote_project(project_name, project_template)
    data['case_overlay'] = apply_case_overlay(data, meta)
    if not data['case_overlay'].get('ok'):
        raise RuntimeError(f"case overlay injection failed: {data['case_overlay']}")
    print(json.dumps(data, ensure_ascii=False))


if __name__ == '__main__':
    main()
