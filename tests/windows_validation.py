"""Run Windows updater checks with a saved log and an explicit blocked status."""
import os
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    for directory in ('.build-deps', '.test-deps'):
        sys.path.insert(0, str(root / directory))
    temporary = root / 'tmp'
    temporary.mkdir(exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temporary)
    tempfile.tempdir = str(temporary)
    results = root / 'local_storage/testing/results'
    results.mkdir(parents=True, exist_ok=True)
    log_path = results / ('windows-validation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.txt')
    with log_path.open('x', encoding='utf-8') as log:
        console = sys.stdout
        class Output:
            def write(self, text):
                console.write(text)
                log.write(text)
            def flush(self):
                console.flush()
                log.flush()
        output = Output()
        output.write('Windows updater checks in ' + str(root) + '\n')
        with redirect_stdout(output), redirect_stderr(output):
            suite = unittest.defaultTestLoader.loadTestsFromName('tests.test_windows_update')
            result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
        if not result.wasSuccessful():
            status, code = 'FAILED: see failures/errors above.', 1
        elif result.skipped:
            status, code = 'BLOCKED: some checks did not run. Windows validation is incomplete.', 2
        else:
            status, code = 'PASSED: all Windows updater checks ran successfully.', 0
        output.write('\n' + status + '\nLog: ' + str(log_path) + '\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
