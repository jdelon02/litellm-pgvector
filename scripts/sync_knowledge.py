#!/usr/bin/env python3
"""Copy repository Markdown into OKF, then index and validate the complete bundle."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


BUNDLE = Path('docs/knowledge')
GENERATED = BUNDLE / 'repository'
MANIFEST = '.sources.json'


def discover_sources(repo):
    """Include tracked and non-ignored new Markdown; exclude bundle and hidden runtime trees."""
    result = subprocess.run(
        ['git', '-C', str(repo), 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.md'],
        check=True, capture_output=True)
    paths = set()
    for name in result.stdout.decode().split('\0'):
        if not name:
            continue
        path = Path(name)
        if path.is_relative_to(BUNDLE) or any(part.startswith('.') for part in path.parts):
            continue
        source = repo / path
        if source.is_file():
            if not source.resolve().is_relative_to(repo.resolve()):
                raise ValueError('Source link leaves the repository: ' + name)
            paths.add(path)
    return sorted(paths)


def destination(path):
    """Reserve index.md/log.md for OKF itself without losing source documents."""
    return path.with_name(path.stem + '.source.md') if path.name in ('index.md', 'log.md') else path


def sync_sources(repo, check=False):
    """Preserve source bytes; update/prune only copies owned by the previous manifest."""
    repo = Path(repo).resolve()
    output = repo / GENERATED
    if any(parent.is_symlink() for parent in (output, output.parent, output.parent.parent)):
        raise ValueError('Generated bundle path must not be a symlink')
    manifest = output / MANIFEST
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    contents, sources = {}, {}
    for path in discover_sources(repo):
        data = (repo / path).read_bytes()
        match = re.match(rb'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)', data, re.S)
        if not match or not re.search(rb'^type:\s*\S+', match[1], re.M):
            raise ValueError(str(path) + ': add OKF frontmatter with a type before syncing')
        target = destination(path).as_posix()
        if target in contents:
            raise ValueError('Generated path collision: ' + target)
        contents[target], sources[target] = data, path.as_posix()

    # Check all paths before any writes, including paths loaded from the old manifest.
    for name in set(previous) | set(contents):
        target = output / name
        if (not target.resolve().is_relative_to(output.resolve()) or target.is_symlink()
                or any(parent.is_symlink() for parent in target.parents if parent != repo)):
            raise ValueError('Unsafe generated path: ' + name)
        if name in contents and target.exists() and name not in previous:
            raise ValueError('Unmanaged file at generated destination: ' + name)
    changed = [name for name, data in contents.items()
               if not (output / name).is_file() or (output / name).read_bytes() != data]
    removed = sorted(set(previous) - set(contents))
    if check:
        if changed or removed or previous != sources:
            raise ValueError('Knowledge copies are stale; run scripts/sync_knowledge.py')
        return len(contents)

    output.mkdir(parents=True, exist_ok=True)
    for name in changed:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[name])
    for name in removed:
        target = output / name
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != output and parent.exists():
            entries = list(parent.iterdir())
            if entries and {p.name for p in entries} != {'index.md'}:
                break
            (parent / 'index.md').unlink(missing_ok=True)
            parent.rmdir()
            parent = parent.parent
    manifest.write_text(json.dumps(sources, indent=2, sort_keys=True) + '\n')
    return len(contents)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--check', action='store_true', help='Check freshness without writing or indexing')
    args = parser.parse_args(argv)
    try:
        count = sync_sources(args.repo, check=args.check)
        print(f'{count} repository Markdown copies {"are current" if args.check else "synchronized"}.', flush=True)
        if not args.check:
            for command in ('index', 'validate'):
                subprocess.run(['okf', command, str(args.repo.resolve() / BUNDLE)], check=True)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
