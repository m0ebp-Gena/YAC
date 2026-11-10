"""Settings-to-updater handover. SPDX-License-Identifier: GPL-3.0-only."""
from pathlib import Path
import os
import subprocess
import sys
import json
import logging
import threading
import zipfile

from modules import chat_int, ft_engine_update, help_int, hints

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
        LOG.warning('GitHub connection failed', exc_info=True)
        raise NoInternet from error
    release = update_yac.newest_release(json.loads(data))
    if update_yac.release_is_newer(root, release):
        update_yac.asset_pair(release, windows=sys.platform == 'win32')
        return release
    return release if ft_engine_update.offer(root, release) else None


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


def ask_engine(root, language, read_key):
    prompt = hints.get_hint(root, language, 'm011')
    chat_int.show_response(prompt)
    while True:
        key = read_key().casefold()
        if key in ('y', 'n'):
            return key
        if key in ('', 'q', '\x03', '\x04'):
            return 'q'
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h027'))
            chat_int.show_response(prompt)


def install_engine(root, language, engine):
    chat_int.show_response(chat_int.label(root, language, 'l364'))
    try:
        ft_engine_update.install(root, *engine)
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        LOG.exception('Optional FT decoder installation failed')
        chat_int.show_response(hints.get_hint(root, language, 'm013'))
    else:
        chat_int.show_response(hints.get_hint(root, language, 'm012'))


def confirm(root, language, read_key):
    global _pending
    _pending = None
    if not supported(root):
        chat_int.show_response(chat_int.label(root, language, 'l327'))
        return False
    def say(label):
        chat_int.show_response(chat_int.label(root, language, label))
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
    import update_yac
    newer = update_yac.release_is_newer(root, release)
    choice = 'n'
    if newer:
        say('l359')
        choice = ask_update(root, language, read_key, release, say)
        if choice == 'q':
            chat_int.show_done(root, language)
            return False
    else:
        say('l358')
    engine = ft_engine_update.offer(root, release)
    if engine:
        engine_choice = ask_engine(root, language, read_key)
        if engine_choice == 'q':
            chat_int.show_done(root, language)
            return False
        if engine_choice == 'n':
            engine = None
    if choice == 'y':
        _pending = (root.resolve(), release, language, engine)
        return True
    if engine:
        install_engine(root, language, engine)
    if newer:
        chat_int.show_done(root, language)
    return False


def ask_update(root, language, read_key, release, say):
    from update_yac import clean_changes

    notes_question = True
    say('l366')
    while True:
        key = read_key().casefold()
        if notes_question and key in {'y', 'n'}:
            if key == 'y':
                help_int.show_paged(root, language, clean_changes(release.get('body') or ''), read_key)
            notes_question = False
            say('l326')
            continue
        if key in ('y', 'n'):
            return key
        if key == 'r':
            help_int.show_paged(root, language, clean_changes(release.get('body') or ''), read_key)
            notes_question = False
            say('l326')
            continue
        if key == 'h':
            chat_int.show_response(help_int.get_help(root, language, 'h027'))
            say('l366' if notes_question else 'l326')
            continue
        if key in ('', 'q', '\x03', '\x04'):
            return 'q'


def run(root):
    """Called only after the radio closes and the application lock is released."""
    global _pending
    plan, _pending = _pending, None
    if plan is not None:
        destination, release, language, engine = plan
        if destination != root.resolve():
            raise RuntimeError('Update selection belongs to another installation')
        import update_yac
        # Installation can replace label files; retain outcomes from this build.
        outcomes = {code: chat_int.label(root, language, code) for code in ('l361', 'l365')}
        chat_int.show_response(chat_int.label(root, language, 'l364'))
        try:
            if sys.platform == 'win32':
                from modules import windows_update
                result = windows_update.run(root, selected_release=release)
            else:
                result = update_yac.run(root, selected_release=release)
        except (OSError, ValueError, KeyError, RuntimeError):
            LOG.exception('Update installation failed')
            result = 1
        if result == REQUEST:
            return 0
        LOG.info('Update installation finished: tag=%s result=%s', release.get('tag_name', '?'), result)
        chat_int.show_response(outcomes['l365' if not result else 'l361'])
        if not result and engine:
            install_engine(root, language, engine)
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
