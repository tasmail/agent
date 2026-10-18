# Agent

## Installation

```
mkdir agent && cd agent
git clone https://github.com/frappe/agent repo
virtualenv env
source env/bin/activate
pip install -e ./repo
cp repo/redis.conf .
cp repo/Procfile .
```

## Running

```
honcho start
```

## Native nginx policy configuration

Host-owned `config.json` supports these opt-in settings:

- `nginx_server_include`: an absolute literal `.conf` path included first in
  public proxy, Agent HTTPS and standalone bench/code-server server blocks.
- `nginx_backend_server_include`: a separate path used only by non-standalone
  bench/code-server HTTP blocks. It does not restrict the Agent control plane.
- `nginx_canonical_forwarding`: boolean, default `false`. When enabled, every
  native proxied location overwrites X-Forwarded-For and X-Real-IP with
  `$remote_addr`. Configure exact trusted proxy peers before enabling it.
- `nginx_external_real_ip`: boolean, default `false`. When enabled, the proxy
  template leaves Cloudflare real-IP ownership to an externally managed HTTP
  include. Stage and validate that replacement first.

Absent or empty include paths leave default rendering unchanged apart from
whitespace. Expressions, glob patterns, relative paths, directive injection and
non-boolean flags are rejected before an output file is opened. Includes are
literal and required so missing policy files fail nginx validation instead of
silently disabling protection. Existing local-only metric listeners are not
included. Server policy must scope its actions to intended public ports.

These settings are read by the common native renderer, including queued proxy
regeneration and new/update/code-server bench paths. Do not edit generated
files or race regeneration with a watcher. Stage policy files before enabling
settings, validate nginx before reload, and remove settings/regenerate before
removing required includes during rollback. Policy files, rate zones, ban state,
trusted CIDRs, deployment and live acceptance remain operator-owned.

## CLI

Agent has a CLI
([ref](https://github.com/frappe/agent/blob/master/agent/cli.py)). You can
access this by activating the env:

```bash
# Path to your agent's Python env might be different
source ./agent/env/bin/activate

agent --help
```

Once you have activated the env, you can access the iPython console:

```bash
agent console
```

This should have the server object instantiated if it was able to find the
`config.json` file. If not you can specify the path (check `agent console --help`).
