#!/usr/bin/env python3
"""
Manifest helper — reads config.deploy.repos.json from stdin and performs
lookups using command-line arguments. Avoids shell quoting issues on Windows
by using sys.argv instead of environment variables.

Usage (pipelines):
  python3 _manifest_helper.py version              < manifest.json
  python3 _manifest_helper.py get <entry> <path>   < manifest.json
  python3 _manifest_helper.py has <entry> <path>   < manifest.json
  python3 _manifest_helper.py keys                  < manifest.json
  python3 _manifest_helper.py entries-for-context <ctx>  < manifest.json
  python3 _manifest_helper.py entries-by-repotype <rt>   < manifest.json
  python3 _manifest_helper.py orphan-handles <entry>     < manifest.json
  python3 _manifest_helper.py perms <entry>              < manifest.json
"""
import sys, json

def eprint(*a, **kw):
    """Print to stderr."""
    print(*a, file=sys.stderr, **kw)

def _out(text):
    """Write a string to stdout as UTF-8 bytes, bypassing CRLF translation."""
    sys.stdout.buffer.write(text.encode('utf-8'))
    sys.stdout.buffer.write(b'\n')

def main():
    # Read stdin as binary and decode UTF-8, then strip any BOM + CRLF
    raw = sys.stdin.buffer.read()
    text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    m = json.loads(text)
    entries = m.get('repoentry', {})

    if len(sys.argv) < 2:
        eprint("Usage: _manifest_helper.py <command> [args...]")
        sys.exit(1)

    cmd = sys.argv[1].strip('\r')

    if cmd == 'version':
        _out(str(m.get('Version', 0)))

    elif cmd == 'get':
        entry = sys.argv[2].strip('\r')
        path = sys.argv[3].strip('\r')
        if entry not in entries:
            eprint(f'ERROR: entry "{entry}" not found in manifest repoentry')
            sys.exit(1)
        node = entries[entry]
        for k in path.split('.'):
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                eprint(f'ERROR: key "{path}" not found in entry "{entry}"')
                sys.exit(1)
        if isinstance(node, list):
            _out(json.dumps(node))
        else:
            _out(str(node))

    elif cmd == 'has':
        entry = sys.argv[2].strip('\r')
        path = sys.argv[3].strip('\r')
        if entry not in entries:
            sys.exit(1)
        node = entries[entry]
        for k in path.split('.'):
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                sys.exit(1)
        sys.exit(0)

    elif cmd == 'keys':
        for k in entries:
            _out(k)

    elif cmd == 'entries-for-context':
        ctx = sys.argv[2].strip('\r')
        for k, v in entries.items():
            rd = v.get('repodir', {})
            if ctx in rd:
                _out(k)

    elif cmd == 'entries-by-repotype':
        repotype = sys.argv[2].strip('\r')
        for k, v in entries.items():
            if v.get('repotype') == repotype:
                _out(k)

    elif cmd == 'orphan-handles':
        entry = sys.argv[2].strip('\r')
        if entry not in entries:
            sys.exit(0)
        ob = entries[entry].get('orphan-branches', {})
        for k in ob:
            _out(k)

    elif cmd == 'perms':
        entry = sys.argv[2].strip('\r')
        if entry not in entries:
            eprint(f'ERROR: entry "{entry}" not found in manifest repoentry')
            sys.exit(1)
        perms = m.get('defaults', {}).get('permissions')
        if not isinstance(perms, dict) or \
           not all(isinstance(perms.get(k), str) and perms.get(k) != ''
                   for k in ('group', 'dir-chmod', 'file-chmod')):
            eprint('ERROR: defaults.permissions must be a dict with non-empty '
                   'group, dir-chmod and file-chmod')
            sys.exit(1)
        if 'permissions' not in entries[entry]:
            resolved = dict(perms)
        elif entries[entry]['permissions'] is None:
            _out('OPTOUT')
            sys.exit(0)
        elif isinstance(entries[entry]['permissions'], dict):
            resolved = dict(perms)
            resolved.update(entries[entry]['permissions'])
        else:
            eprint(f'ERROR: entry "{entry}" permissions must be a dict or null')
            sys.exit(1)
        group = resolved.get('group')
        group = '' if group is None else str(group)
        _out(f"{group}\t{resolved['dir-chmod']}\t{resolved['file-chmod']}")

    else:
        eprint(f'Unknown command: {cmd}')
        sys.exit(1)

if __name__ == '__main__':
    main()