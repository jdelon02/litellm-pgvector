#!/usr/bin/env python3
"""Embed OKF concept bodies and append new chunks to the primary vector store."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib import parse

import requests


MODEL = 'text-embedding-ada-002'
EMBEDDING_BASE_URL = 'https://nano-gpt.com/api/v1'
DIMENSIONS = 1536
BUNDLE = Path('docs/knowledge')


def read_env(path):
    """Read simple dotenv assignments as data; never execute shell expressions."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        line = line.removeprefix('export ')
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key.strip()):
            raise ValueError('Invalid dotenv assignment (values are not printed)')
        value = value.strip()
        if value[:1] in ('"', "'"):
            quote = value[0]
            end = value.rfind(quote)
            if end == 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith('#')):
                raise ValueError('Invalid quoted dotenv value')
            value = value[1:end]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        values[key.strip()] = value
    return values


def resolve_value(value):
    value = str(value or '')
    match = re.fullmatch(r'\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)|env:([A-Za-z_]\w*)', value)
    if match:
        value = os.environ.get(next(v for v in match.groups() if v), '')
        if not value:
            raise ValueError('A Hermes credential environment reference is unset; export it before running')
    return value


def validate_url(url):
    parsed = parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('API base URL must be HTTP(S), without credentials, query, or fragment')
    return url.rstrip('/')


def connection_settings(env, hermes_path):
    embedding_key = resolve_value(env.get('NANOGPT_API_KEY'))
    if not embedding_key:
        raise ValueError('Set NANOGPT_API_KEY in the project .env or process environment')
    vector_url = validate_url(env.get('rag_base_url', ''))
    vector_key = resolve_value(env.get('rag_api_key'))
    if vector_key:
        return EMBEDDING_BASE_URL, embedding_key, vector_url, vector_key
    # Preserve the legacy vector-service credential fallback; never send the
    # NanoGPT key to the vector service or a Hermes proxy key to NanoGPT.
    try:
        import yaml
    except ImportError:
        raise ValueError('PyYAML is required: python3 -m pip install -r scripts/requirements-rag.txt') from None
    try:
        config = yaml.safe_load(hermes_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        raise ValueError('Cannot read Hermes YAML configuration; use --hermes-config') from None
    model = config.get('model', {})
    if not isinstance(model, dict):
        raise ValueError('Hermes config must contain model.api_key for the vector service fallback')
    vector_key = resolve_value(model.get('api_key'))
    if not vector_key:
        raise ValueError('Missing API key; configure Hermes model.api_key or rag_api_key')
    return EMBEDDING_BASE_URL, embedding_key, vector_url, vector_key


def command_json(args):
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def chunk_text(text, max_chars=3000):
    """Split on headings outside fences, then bound large sections without losing text."""
    sections, lines, title, fence = [], [], '', None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        heading = re.match(r'^#{1,6}\s+(.+?)\s*$', line) if fence is None else None
        if heading:
            if lines:
                sections.append((title, ''.join(lines)))
            lines, title = [], heading[1]
        lines.append(line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
    if lines:
        sections.append((title, ''.join(lines)))
    chunks = []
    for title, content in sections:
        while content:
            end = min(len(content), max_chars)
            if end < len(content):
                paragraph = content.rfind('\n\n', 0, end)
                if paragraph >= end // 2:
                    end = paragraph + 2
                else:
                    boundary = content.rfind('\n', 0, end)
                    if boundary >= end // 2:
                        end = boundary + 1
            chunks.append({'section': title, 'content': content[:end]})
            content = content[end:]
    return chunks


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def collect_chunks(repo, max_chars):
    repo = repo.resolve()
    bundle = repo / BUNDLE
    concepts = command_json(['okf', 'list', str(bundle)])['concepts']
    chunks = []
    for entry in sorted(concepts, key=lambda c: c['id']):
        concept = command_json(['okf', 'show', str(bundle), entry['id']])['concept']
        path = Path(concept['path']).resolve()
        if not path.is_relative_to(bundle.resolve()):
            raise ValueError('OKF concept path leaves the knowledge bundle')
        metadata = {k: concept[k] for k in ('title', 'type', 'tags', 'status', 'trust_tier', 'stale') if k in concept}
        metadata.update({'project_id': repo.name, 'concept_id': concept['id'],
                         'filename': path.name, 'source_path': path.relative_to(repo).as_posix(),
                         'source_tool': 'okf', 'embedding_model': MODEL})
        for index, chunk in enumerate(chunk_text(concept['body'], max_chars)):
            if not chunk['content'].strip():
                continue
            meta = dict(metadata, section=chunk['section'], chunk_index=index)
            meta['chunk_id'] = digest({'content': chunk['content'], 'metadata': meta})
            chunks.append({'content': chunk['content'], 'metadata': meta})
    return chunks


class APIHTTPError(ValueError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(f'API returned HTTP {status}: {detail}')


def request_json(url, key, body=None):
    if not isinstance(key, str) or not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError('API key must contain printable non-whitespace ASCII characters')
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    method = 'POST' if body is not None else 'GET'
    if os.environ.get('RAG_DEBUG', '').lower() in ('1', 'true', 'yes'):
        debug = f'RAG DEBUG: {method} {url}\nContent-Type: application/json\nAuthorization: Bearer [REDACTED]'
        if body is not None and parse.urlsplit(url).path.rstrip('/').endswith('/embeddings'):
            debug += '\nBody: ' + json.dumps(body, allow_nan=False)
        debug = debug.replace(key, '[REDACTED]').replace(json.dumps(key)[1:-1], '[REDACTED]')
        print(debug, file=sys.stderr, flush=True)
    try:
        if body is None:
            response = requests.get(url, headers=headers, timeout=90, allow_redirects=False)
        else:
            response = requests.post(url, headers=headers, json=body, timeout=90, allow_redirects=False)
        with response:
            if not 200 <= response.status_code < 300:
                detail = response.text.replace(key, '[REDACTED]').replace(json.dumps(key)[1:-1], '[REDACTED]')
                raise APIHTTPError(response.status_code, detail or '(empty response body)')
            try:
                return response.json()
            except ValueError:
                raise ValueError('API returned an invalid JSON response') from None
    except requests.RequestException:
        raise ValueError('API connection failed or timed out; check endpoints and connectivity') from None


def post_json(url, key, body):
    return request_json(url, key, body)


def embed_batch(texts, proxy_url, key, post=post_json):
    """Send a synchronous array-of-texts request; retry transient HTTP failures."""
    payload = {'model': MODEL, 'input': texts, 'encoding_format': 'float'}
    for attempt in range(4):
        try:
            return post(proxy_url.rstrip('/') + '/embeddings', key, payload)
        except APIHTTPError as exc:
            if exc.status not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            delay = 2 ** attempt
            print(f'Embedding HTTP {exc.status}; retry {attempt + 1}/3 in {delay}s.',
                  file=sys.stderr, flush=True)
            time.sleep(delay)


def resolve_store_name(vector_url, key, name, get=request_json):
    root = vector_url.rstrip('/').removesuffix('/v1')
    result = get(root + '/v1/vector_stores?limit=100', key)
    if not isinstance(result.get('data'), list) or not isinstance(result.get('has_more'), bool):
        raise ValueError('Invalid vector-store listing response')
    matches = [row for row in result['data'] if row.get('name') == name]
    if len(matches) > 1:
        raise ValueError('Vector-store name is ambiguous; choose a unique name')
    # This backend orders by creation date but paginates by ID, so subsequent
    # pages cannot establish uniqueness reliably. Never silently pick a store.
    if result['has_more']:
        raise ValueError('Vector-store listing is incomplete; name lookup requires at most 100 stores until backend pagination is fixed')
    if not matches:
        raise ValueError('Vector-store name not found; create it first or check the configured name')
    store_id = matches[0].get('id')
    if not isinstance(store_id, str) or not store_id:
        raise ValueError('Vector-store listing returned an invalid ID')
    return store_id


def embedding_vectors(response, count):
    rows = response.get('data', [])
    if len(rows) != count or sorted(row.get('index', -1) for row in rows) != list(range(count)):
        raise ValueError('Embedding response count/index mismatch')
    vectors = []
    for row in sorted(rows, key=lambda row: row['index']):
        vector = row.get('embedding', [])
        if len(vector) != DIMENSIONS or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
            raise ValueError(f'Embedding must contain {DIMENSIONS} finite numbers')
        vectors.append(vector)
    return vectors


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def upload_chunks(chunks, state_path, proxy_url, proxy_key, vector_url, vector_key, store_id, post=post_json, batch_size=16):
    if type(batch_size) is not int or not 1 <= batch_size <= 2048:
        raise ValueError('Batch size must be an integer from 1 to 2048')
    state = json.loads(state_path.read_text()) if state_path.exists() else {'uploaded': {}}
    if state.get('pending'):
        raise ValueError('Previous upload is unconfirmed; inspect the local pending batch before retrying')
    current_ids = {c['metadata']['chunk_id'] for c in chunks}
    old = set(state['uploaded']) - current_ids
    if old:
        print(f'Warning: {len(old)} previously uploaded chunks are no longer current; the append-only API retains them.', file=sys.stderr)
    remaining = [c for c in chunks if c['metadata']['chunk_id'] not in state['uploaded']]
    vector_root = vector_url.rstrip('/').removesuffix('/v1')
    uploaded = 0
    batches = (len(remaining) + batch_size - 1) // batch_size
    for offset in range(0, len(remaining), batch_size):
        batch = remaining[offset:offset + batch_size]
        print(f'Embedding batch {offset // batch_size + 1}/{batches}: {len(batch)} texts; model {MODEL}.', flush=True)
        response = embed_batch([c['content'] for c in batch], proxy_url, proxy_key, post=post)
        vectors = embedding_vectors(response, len(batch))
        usage = response.get('usage')
        if isinstance(usage, dict) and type(usage.get('total_tokens')) is int:
            print(f'Embedding usage: total_tokens={usage["total_tokens"]}.', flush=True)
        ids = [c['metadata']['chunk_id'] for c in batch]
        # Persist intent before the non-idempotent insert. A timeout may mean it committed.
        state['pending'] = ids
        save_state(state_path, state)
        result = post(vector_root + '/v1/vector_stores/' + parse.quote(store_id, safe='') + '/embeddings/batch',
                      vector_key, {'embeddings': [dict(c, embedding=v) for c, v in zip(batch, vectors)]})
        rows = result.get('data', [])
        if len(rows) != len(batch) or any(not row.get('id') for row in rows):
            raise ValueError('Vector-store response did not confirm all inserted chunks')
        state['uploaded'].update({chunk_id: True for chunk_id in ids})
        state.pop('pending')
        save_state(state_path, state)
        uploaded += len(batch)
        print(f'Uploaded {uploaded}/{len(remaining)} new chunks.', flush=True)
    return uploaded


@contextmanager
def upload_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another RAG upload is already running') from None
        yield


def check_staged_markdown(repo):
    """Do not ingest working-tree Markdown that differs from the proposed commit."""
    for args in (['diff', '--name-only', '-z', '--', '*.md'],
                 ['ls-files', '--others', '--exclude-standard', '-z', '--', '*.md']):
        paths = subprocess.check_output(['git', '-C', str(repo), *args])
        if paths:
            raise ValueError('Stage or stash Markdown changes before RAG pre-commit; partial document commits are not supported')


def prepare_commit_bundle(repo):
    """Refresh OKF and stage only navigation indexes changed by that refresh."""
    repo = repo.resolve()
    check_staged_markdown(repo)
    bundle = repo / BUNDLE
    before = {p: p.read_bytes() for p in bundle.rglob('index.md')}
    subprocess.run([sys.executable, str(repo / 'scripts/sync_knowledge.py'), '--repo', str(repo)], check=True)
    changed = []
    for path in sorted(bundle.rglob('index.md')):
        if before.get(path) == path.read_bytes():
            continue
        relative = path.relative_to(repo).as_posix()
        ignored = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--quiet', '--', relative])
        if ignored.returncode not in (0, 1):
            raise ValueError('Could not determine which generated indexes are Git-ignored')
        if ignored.returncode == 1:
            changed.append(relative)
    if changed:
        subprocess.run(['git', '-C', str(repo), 'add', '--', *changed], check=True)
        print(f'Staged {len(changed)} refreshed OKF indexes for this commit.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--dry-run', action='store_true', help='Inspect OKF only; no credentials, network, or state writes')
    parser.add_argument('--hook', action='store_true', help='Pre-commit mode: refresh OKF, stage changed indexes, and upload; skip unset store')
    parser.add_argument('--hermes-config', type=Path)
    parser.add_argument('--chunk-chars', type=int, default=3000)
    parser.add_argument('--batch-size', type=int, help='Texts per embedding request (1–2048); overrides rag_batch_size, default 16')
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        env = read_env(repo / '.env')
        for key in ('primary_vector_store_name', 'primary_vector_store_id', 'vector_stores', 'rag_base_url', 'rag_api_key', 'rag_batch_size', 'NANOGPT_API_KEY'):
            if key in os.environ:
                env[key] = os.environ[key]
        if env.get('primary_vector_store_id', '').strip():
            raise ValueError('Replace primary_vector_store_id with primary_vector_store_name using the store name, not its ID')
        store_name = env.get('primary_vector_store_name', '')
        store = None
        if args.hook and not store_name.strip():
            print('RAG upload skipped: primary_vector_store_name is empty.')
            return 0
        stores = json.loads(env.get('vector_stores') or '[]')
        if not isinstance(stores, list) or any(not isinstance(s, str) or not s.strip() for s in stores):
            raise ValueError('vector_stores must be a JSON array of nonempty store names, or []')
        if args.chunk_chars < 100:
            raise ValueError('--chunk-chars must be at least 100')
        try:
            batch_size = args.batch_size if args.batch_size is not None else int(env.get('rag_batch_size') or '16')
        except ValueError:
            raise ValueError('Batch size must be an integer from 1 to 2048') from None
        if not 1 <= batch_size <= 2048:
            raise ValueError('Batch size must be an integer from 1 to 2048')
        if not args.dry_run and not store_name.strip():
            raise ValueError('Set primary_vector_store_name in .env before uploading')
        if args.hook:
            check_staged_markdown(repo)
        settings = None
        if not args.dry_run:
            hermes = args.hermes_config
            if hermes is None:
                hermes = Path.home() / '.hermes/config.yml'
                if not hermes.exists():
                    hermes = Path.home() / '.hermes/config.yaml'
            settings = connection_settings(env, hermes)
            store = resolve_store_name(settings[2], settings[3], store_name)
        if args.hook and not args.dry_run:
            prepare_commit_bundle(repo)
        chunks = collect_chunks(repo, args.chunk_chars)
        print(f'OKF: {len({c["metadata"]["concept_id"] for c in chunks})} documents, {len(chunks)} chunks; model {MODEL}, {DIMENSIONS} dimensions.')
        if args.dry_run:
            print('Dry run: no embeddings requested or documents uploaded.')
            return 0
        proxy_url, proxy_key, vector_url, vector_key = settings
        target = digest([vector_url, store, proxy_url, MODEL, DIMENSIONS])
        state_path = repo / '.rag' / (target + '.json')
        with upload_lock(repo / '.rag/upload.lock'):
            count = upload_chunks(chunks, state_path, *settings, store, batch_size=batch_size)
        print(f'Complete: {count} new chunks uploaded; {len(chunks) - count} already confirmed locally.')
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        # External payloads and credential files must not appear in tracebacks.
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + ': check configuration and tool availability'
        print('RAG: ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
