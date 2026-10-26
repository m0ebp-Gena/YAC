"""Settings-to-updater handover. SPDX-License-Identifier: GPL-3.0-only."""
from pathlib import Path
import os
import subprocess
import sys
import json
import logging
import threading

from modules import chat_int, help_int

REQUEST = 75
LOG = logging.getLogger('yac.update')
LOG.addHandler(logging.NullHandler())
_pending = None


class LookupFinished(Exception):
    pass


class NoInternet(RuntimeError):
    pass


def lookup(root):
    """Check release metadata only; never download a package or change files."""
    import update_yac
    try:
        data = update_yac.fetch(update_yac.API, 2 * 1024 * 1024)
    except OSError as error:
        raise NoInternet from error
    release = update_yac.newest_release(json.loads(data))
    marker = root / 'release.json'
    current = json.loads(marker.read_text()) if marker.is_file() else {}
    if current.get('tag') == release['tag_name'] or current.get('published_at', '') >= release['published_at']:
        return None
    update_yac.asset_pair(release, windows=sys.platform == 'win32')
    return release


def _lookup_while_cancellable(root, read_key):
    finished = threading.Event()
    result = {}
    def worker():
        try:
            result['release'] = lookup(root)
        except Exception as error:
            result['error'] = error
        finally:
            finished.set()
    threading.Thread(target=worker, daemon=True).start()
    def poll():
        if finished.is_set():
            raise LookupFinished
    while not finished.is_set():
        try:
            key = read_key(idle_callback=poll).casefold()
        except LookupFinished:
            break
        if key in {'q', '\x03', '\x04'}:
            return False, None
    if 'error' in result:
        raise result['error']
    return True, result.get('release')


def supported(root):
    if sys.platform == 'win32':
        return bool(getattr(sys, 'frozen', False))
    if sys.platform in ('linux', 'darwin'):
        expected = Path.home() / ('Applications' if sys.platform == 'darwin' else '.local') / 'yac'
        return root.resolve() == expected.resolve() and (root / 'update_yac.py').is_file()
    return False


def confirm(root, language, read_key):
    global _pending
    _pending = None
    if not supported(root):
        chat_int.show_response(chat_int.label(root, language, 'l327'))
        return False
    def say(label):
        chat_int.show_response(chat_int.label(root, language, label))
    chat_int.show_response(help_int.get_help(root, language, 'h027'))
    say('l357')
    try:
        completed, release = _lookup_while_cancellable(root, read_key)
    except NoInternet:
        LOG.info('GitHub could not be reached')
        say('l360')
        return False
    except (OSError, ValueError, KeyError, RuntimeError):
        LOG.exception('Update lookup failed')
        say('l361')
        return False
    if not completed:
        chat_int.show_done(root, language)
        return False
    if release is None:
        say('l358')
        return False
    say('l359')
    import update_yac
    notes_question = True
    say('l366')
    while True:
        key = read_key().casefold()
        if notes_question and key in {'y', 'n'}:
            if key == 'y':
                help_int.show_paged(root, language, update_yac.clean_changes(release.get('body') or ''), read_key)
            notes_question = False
            say('l326')
            continue
        if key == 'y':
            _pending = (root.resolve(), release, language)
            return True
        if key == 'r':
            help_int.show_paged(root, language, update_yac.clean_changes(release.get('body') or ''), read_key)
            notes_question = False
            say('l326')
            continue
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h027'))
            say('l366' if notes_question else 'l326')
            continue
        if key in ('n', 'q', '\x03', '\x04'):
            chat_int.show_done(root, language)
            return False


def run(root):
    """Called only after the radio closes and the application lock is released."""
    global _pending
    plan, _pending = _pending, None
    if plan is not None:
        if plan[0] != root.resolve():
            raise RuntimeError('Update selection belongs to another installation')
        import update_yac
        language = plan[2]
        # Installation can replace label files; retain outcomes from this build.
        outcomes = {code: chat_int.label(root, language, code) for code in ('l361', 'l365')}
        chat_int.show_response(chat_int.label(root, language, 'l364'))
        try:
            if sys.platform == 'win32':
                from modules import windows_update
                result = windows_update.run(root, selected_release=plan[1])
            else:
                result = update_yac.run(root, selected_release=plan[1])
        except (OSError, ValueError, KeyError, RuntimeError):
            LOG.exception('Update installation failed')
            result = 1
        if result == REQUEST:
            return 0
        LOG.info('Update installation finished: tag=%s result=%s', plan[1].get('tag_name', '?'), result)
        chat_int.show_response(outcomes['l365' if not result else 'l361'])
        chat_int.finish_response()
        os.execv(sys.executable, [sys.executable,
                                 *([] if sys.platform == 'win32' else [str(root / 'yac.py')]),
                                 *sys.argv[1:]])
        return 0
    if sys.platform == 'win32':
        import update_yac
        result = update_yac.windows_main(root)
        if result == REQUEST:
            return 0  # The staged Windows installer must wait for this EXE to exit.
        if result:
            try:
                input('Press Enter to return to YAC.')
            except (EOFError, KeyboardInterrupt):
                return result
        os.execv(sys.executable, [sys.executable, *sys.argv[1:]])
    else:
        result = subprocess.run([sys.executable, str(root / 'update_yac.py')])
        if result.returncode:
            try:
                input('Update did not complete. Check the internet connection if needed. Press Enter to return to YAC.')
            except (EOFError, KeyboardInterrupt):
                return result.returncode
        # Load a fresh process: installed modules may have changed.
        os.execv(sys.executable, [sys.executable, str(root / 'yac.py'), *sys.argv[1:]])
    return 0
