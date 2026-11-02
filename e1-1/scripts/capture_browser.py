#!/usr/bin/env python3
"""Capture the real Firefox window, including its address bar, on an X display.

Usage: xvfb-run -a -s '-screen 0 1280x900x24 -ac' python scripts/capture_browser.py
Requires Firefox, Xvfb, xwininfo, and scrot. No screenshot is synthesized.
"""

import os
from pathlib import Path
import signal
import subprocess
import time

from verify import Recorder, ROOT


profile = ROOT / 'practice/firefox-profile'
profile.mkdir(parents=True, exist_ok=True)
settings = {
    'browser.shell.checkDefaultBrowser': 'false',
    'browser.aboutwelcome.enabled': 'false',
    'browser.startup.homepage_override.mstone': '"ignore"',
    'browser.startup.firstrunSkipsHomepage': 'true',
    'datareporting.policy.dataSubmissionPolicyBypassNotification': 'true',
}
(profile / 'user.js').write_text('\n'.join(
    f'user_pref("{key}", {value});' for key, value in settings.items()) + '\n')
screenshots = ROOT / 'screenshots'
screenshots.mkdir(exist_ok=True)
record = Recorder('11-browser-capture')
record.run(['firefox', '--version'])
args = ['firefox', '--no-remote', '--profile', str(profile),
        '--width', '1280', '--height', '900', '--new-window', 'http://localhost:18080']
record.append('$ ' + ' '.join(args) + '\n')
with (ROOT / 'practice/firefox-startup.log').open('w') as startup:
    browser = subprocess.Popen(args, stdout=startup, stderr=subprocess.STDOUT,
                               start_new_session=True)
    try:
        for _ in range(25):
            tree = subprocess.run(['xwininfo', '-root', '-tree'], text=True,
                                  capture_output=True).stdout
            if 'Codyssey E1-1' in tree:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Firefox did not display the expected page; inspect practice/firefox-startup.log')
        time.sleep(2)
        record.run(['xwininfo', '-root', '-tree'])
        record.run(['scrot', str(screenshots / 'web-18080.png')])
    finally:
        try:
            os.killpg(browser.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            browser.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(browser.pid, signal.SIGKILL)
            browser.wait()
