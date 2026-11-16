"""Disk-based backup/restore for large projects; no credentials or network needed."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.backup import export_backup, restore_backup
from studio.errors import StudioError
from studio.storage import Store


def main():
    parser = argparse.ArgumentParser(description='Export/import local Fashion AI Studio backups without loading the ZIP into RAM.')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--data-dir', required=True)
    export.add_argument('--output', required=True)
    restore = commands.add_parser('restore')
    restore.add_argument('--input', required=True)
    restore.add_argument('--parent', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export':
            output = Path(args.output).resolve()
            if output.exists():
                raise StudioError('Tệp đầu ra đã tồn tại. Chọn tên mới để giữ bản sao lưu cũ.')
            print(export_backup(Store(args.data_dir), destination=output))
        else:
            print(restore_backup(Path(args.input), Path(args.parent)))
    except StudioError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f'Backup failed ({type(error).__name__}); verify paths and archive integrity.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
