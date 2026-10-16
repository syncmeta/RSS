#!/bin/sh
# Run manually on the Mac; no background schedule is installed.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -n "${RSS_BACKUP_PYTHON:-}" ]; then
    backup_python=$RSS_BACKUP_PYTHON
elif [ -x /opt/homebrew/bin/python3.12 ]; then
    backup_python=/opt/homebrew/bin/python3.12
else
    backup_python=python3
fi
"$backup_python" -c 'import sys, tarfile; assert sys.version_info >= (3, 11) and hasattr(tarfile, "data_filter"), "Use Python 3.11+ with tarfile.data_filter, e.g. RSS_BACKUP_PYTHON=/path/to/python3.12"'
exec "$backup_python" "$script_dir/pull.py" "$@"
