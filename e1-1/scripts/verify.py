#!/usr/bin/env python3
"""Run E1-1 exercises and record actual commands, stdout, and stderr.

Usage: python scripts/verify.py terminal|docker|git
Docker phase creates its own resources and refuses to replace existing ones.
"""

import argparse
import hashlib
import os
from pathlib import Path
import pty
import re
import select
import shlex
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / 'logs'
PREFIX = 'codyssey-e1-1-check'
IMAGE = 'codyssey-e1-1-web:verified'
WEB = PREFIX + '-web'
BIND = PREFIX + '-bind'
UBUNTU = PREFIX + '-ubuntu'
VOLUME = PREFIX + '-data'
V1 = PREFIX + '-vol-before'
V2 = PREFIX + '-vol-after'


def clean(text):
    text = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text.replace('\r\n', '\n')).replace('\r', '')
    text = re.sub(r'(?im)^(user\.email=).*$', r'\1<이메일 마스킹>', text)
    text = re.sub(r'(?im)^([^\n=]*(?:token|password|secret|extraheader|credential)[^\n=]*=).*$',
                  r'\1<인증 설정 마스킹>', text)
    text = re.sub(r'\bgh[pousr]_[A-Za-z0-9_]+', '<토큰 마스킹>', text)
    return '\n'.join(line.rstrip() for line in text.split('\n'))


class Recorder:
    def __init__(self, name):
        LOGS.mkdir(exist_ok=True)
        self.path = LOGS / (name + '.log')
        self.path.write_text('')

    def append(self, text):
        text = clean(text)
        with self.path.open('a') as file:
            file.write(text)
        print(text, end='', flush=True)

    def run(self, args, cwd=ROOT, expected=0, stdin=None):
        self.append('$ ' + shlex.join(args) + '\n')
        result = subprocess.run(args, cwd=cwd, input=stdin, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.append(result.stdout)
        if result.stdout and not result.stdout.endswith('\n'):
            self.append('\n')
        self.append(f'[exit={result.returncode}]\n\n')
        if result.returncode != expected:
            raise RuntimeError(f'Unexpected exit code: {shlex.join(args)}')
        return result.stdout

    def interactive(self, args, commands, detach=False):
        self.append('$ ' + shlex.join(args) + '\n')
        master, slave = pty.openpty()
        env = dict(os.environ, TERM='xterm')
        process = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave,
                                   cwd=ROOT, env=env, start_new_session=True)
        os.close(slave)
        captured = bytearray()

        def read_for(seconds):
            until = time.monotonic() + seconds
            while time.monotonic() < until:
                if not select.select([master], [], [], 0.1)[0]:
                    if process.poll() is not None:
                        break
                    continue
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                captured.extend(data)

        try:
            read_for(1)
            for command in commands:
                os.write(master, command.encode() + b'\n')
                read_for(0.7)
            if detach:
                os.write(master, b'\x10\x11')
            read_for(1)
            status = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
        self.append(captured.decode(errors='replace'))
        if detach:
            self.append('\n[Ctrl+P, Ctrl+Q: detach]\n')
        self.append(f'\n[exit={status}]\n\n')
        # This Docker CLI reports a detach escape as exit 1. Verify the
        # container's running state separately; preserve the actual exit code.
        expected_detach = detach and status == 1 and b'read escape sequence' in captured
        if status and not expected_detach:
            raise RuntimeError('Interactive Docker command failed')

    def state(self, name, expected):
        status = self.run(['docker', 'inspect', '--format', '{{.State.Status}}', name]).strip()
        if status != expected:
            raise RuntimeError(f'Expected {name} to be {expected}, got {status}')


def terminal():
    os.umask(0o022)
    r = Recorder('01-terminal')
    r.run(['pwd'])
    r.run(['ls', '-la'])
    r.run(['mkdir', '-p', 'practice/terminal', 'practice/permissions'])
    work = ROOT / 'practice/terminal'
    r.run(['bash', '-c', 'cd practice/terminal && pwd'])
    r.run(['touch', 'empty.txt', '.hidden'], cwd=work)
    r.run(['bash', '-c', "printf 'Hello Codyssey CLI\\n' > original.txt"], cwd=work)
    r.run(['ls', '-la'], cwd=work)
    r.run(['cat', 'original.txt'], cwd=work)
    r.run(['cp', 'original.txt', 'copy.txt'], cwd=work)
    r.run(['mv', 'copy.txt', 'renamed.txt'], cwd=work)
    r.run(['mkdir', '-p', 'archive'], cwd=work)
    r.run(['mv', 'renamed.txt', 'archive/renamed.txt'], cwd=work)
    r.run(['cat', 'archive/renamed.txt'], cwd=work)
    r.run(['rm', 'archive/renamed.txt'], cwd=work)
    r.run(['rmdir', 'archive'], cwd=work)
    r.run(['ls', '-la'], cwd=work)
    r = Recorder('02-permissions')
    work = ROOT / 'practice/permissions'
    r.run(['bash', '-c', "printf 'permission practice\\n' > sample.txt"], cwd=work)
    r.run(['mkdir', '-p', 'sample-dir'], cwd=work)
    r.run(['chmod', '600', 'sample.txt'], cwd=work)
    r.run(['chmod', '700', 'sample-dir'], cwd=work)
    r.run(['stat', '-c', '%a %A %n', 'sample.txt', 'sample-dir'], cwd=work)
    r.run(['chmod', '644', 'sample.txt'], cwd=work)
    r.run(['chmod', '755', 'sample-dir'], cwd=work)
    r.run(['stat', '-c', '%a %A %n', 'sample.txt', 'sample-dir'], cwd=work)
    r.run(['chmod', '000', 'sample.txt'], cwd=work)
    r.run(['cat', 'sample.txt'], cwd=work, expected=1)
    r.run(['stat', '-c', '%a %A %n', 'sample.txt'], cwd=work)
    r.run(['chmod', '644', 'sample.txt'], cwd=work)
    r.run(['cat', 'sample.txt'], cwd=work)
    r = Recorder('03-environment')
    for args in [['date', '-Iseconds'], ['cat', '/etc/os-release'],
                 ['bash', '-c', 'printf "Shell=%s\\nTERM=%s\\n" "$SHELL" "$TERM"'],
                 ['bash', '-c', 'command -v code'], ['docker', '--version'],
                 ['git', '--version']]:
        r.run(args)


def docker():
    # Prevent removal or modification of resources from another run.
    names = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{.Names}}'], text=True).splitlines()
    volumes = subprocess.check_output(['docker', 'volume', 'ls', '--format', '{{.Name}}'], text=True).splitlines()
    if any(name in names for name in [WEB, BIND, UBUNTU, V1, V2]) or VOLUME in volumes:
        raise RuntimeError('Exercise resources already exist; inspect them before re-running.')
    r = Recorder('04-docker-info')
    r.run(['docker', '--version'])
    r.run(['docker', 'info'])
    r = Recorder('05-hello-world')
    r.run(['docker', 'pull', 'hello-world:latest'])
    r.run(['docker', 'run', '--rm', 'hello-world:latest'])
    r = Recorder('06-ubuntu-lifecycle')
    r.run(['docker', 'pull', 'ubuntu:22.04'])
    r.run(['docker', 'run', '-dit', '--name', UBUNTU, 'ubuntu:22.04', 'bash'])
    r.interactive(['docker', 'exec', '-it', UBUNTU, 'bash'],
                  ["echo 'Hello Codyssey exec'", 'pwd', 'ls /', 'exit'])
    r.state(UBUNTU, 'running')
    r.interactive(['docker', 'attach', UBUNTU], ["echo 'Hello Codyssey attach'"], detach=True)
    r.state(UBUNTU, 'running')
    r.interactive(['docker', 'attach', UBUNTU], ['exit'])
    r.state(UBUNTU, 'exited')
    r.run(['docker', 'start', UBUNTU])
    r.run(['docker', 'stop', UBUNTU])
    r.run(['docker', 'ps', '-a', '--filter', 'name=' + UBUNTU])
    r = Recorder('07-web-build-run')
    r.run(['docker', 'build', '--progress=plain', '-t', IMAGE, '.'])
    r.run(['docker', 'images', IMAGE])
    r.run(['docker', 'run', '-d', '--name', WEB, '-p', '127.0.0.1:18080:80', IMAGE])
    r.run(['docker', 'ps', '--filter', 'name=' + WEB])
    r.run(['docker', 'port', WEB])
    time.sleep(1)
    r.run(['curl', '--fail', '--silent', '--show-error', '-i', 'http://localhost:18080'])
    r.run(['docker', 'logs', WEB])
    r.run(['docker', 'stats', '--no-stream', WEB])
    r.run(['docker', 'stop', WEB])
    r.run(['docker', 'ps', '-a', '--filter', 'name=' + WEB])
    r.run(['docker', 'start', WEB])
    r = Recorder('08-bind-mount')
    r.run(['mkdir', '-p', 'practice/bind-site'])
    r.run(['cp', 'app/index.html', 'practice/bind-site/index.html'])
    r.run(['docker', 'run', '-d', '--name', BIND, '-p', '127.0.0.1:18081:80',
           '--mount', f'type=bind,source={ROOT / "practice/bind-site"},target=/usr/share/nginx/html,readonly', IMAGE])
    r.run(['docker', 'port', BIND])
    time.sleep(1)
    r.run(['curl', '--fail', '--silent', '--show-error', 'http://localhost:18081'])
    r.run(['bash', '-c', "printf '<h1>Codyssey bind mount UPDATED</h1>\\n' > practice/bind-site/index.html"])
    r.run(['cat', 'practice/bind-site/index.html'])
    output = r.run(['curl', '--fail', '--silent', '--show-error', 'http://localhost:18081'])
    if 'Codyssey bind mount UPDATED' not in output:
        raise RuntimeError('Bind mount update not visible')
    r.run(['docker', 'inspect', '--format', '{{.Id}} {{.State.StartedAt}} {{range .Mounts}}{{.Type}} {{.RW}}{{end}}', BIND])
    r = Recorder('09-volume-persistence')
    r.run(['docker', 'volume', 'create', VOLUME])
    r.run(['docker', 'run', '-d', '--name', V1, '--mount', f'type=volume,source={VOLUME},target=/data', 'ubuntu:22.04', 'sleep', 'infinity'])
    r.run(['docker', 'exec', V1, 'bash', '-lc', "printf 'Codyssey persistent data\\n' > /data/hello.txt; cat /data/hello.txt; sha256sum /data/hello.txt"])
    r.run(['docker', 'stop', V1])
    r.run(['docker', 'rm', V1])
    r.run(['docker', 'ps', '-a', '--filter', 'name=' + V1])
    r.run(['docker', 'run', '-d', '--name', V2, '--mount', f'type=volume,source={VOLUME},target=/data', 'ubuntu:22.04', 'sleep', 'infinity'])
    output = r.run(['docker', 'exec', V2, 'bash', '-lc', 'cat /data/hello.txt; sha256sum /data/hello.txt'])
    expected = hashlib.sha256(b'Codyssey persistent data\n').hexdigest()
    if expected not in output:
        raise RuntimeError('Volume data mismatch')
    r.run(['docker', 'volume', 'inspect', '--format', '{{.Name}} {{.Driver}} {{.Scope}}', VOLUME])
    r.run(['docker', 'stop', V2])
    r.run(['docker', 'rm', V2])


def git():
    r = Recorder('10-git-github')
    r.run(['git', 'config', '--global', '--list'])
    r.run(['git', 'remote', '-v'])
    r.run(['git', 'branch', '--show-current'])
    r.run(['git', 'log', '-1', '--format=%h %s'])
    r.run(['git', 'ls-remote', 'origin', 'refs/heads/main'])
    # Only select public repository metadata; never request or log credentials.
    r.run(['bash', '-o', 'pipefail', '-c',
           'curl --fail --silent --show-error https://api.github.com/repos/AerideS/Codyssey '
           '| python -c \'import json,sys; d=json.load(sys.stdin); '
           'print(json.dumps({k:d[k] for k in ["full_name","private","default_branch","html_url"]}, indent=2))\''])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['terminal', 'docker', 'git'])
    arguments = parser.parse_args()
    {'terminal': terminal, 'docker': docker, 'git': git}[arguments.phase]()
