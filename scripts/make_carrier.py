"""Generate a transparent title carrier from local snapshot + plan (requires FFmpeg)."""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', required=True)
    p.add_argument('--plan', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    snap = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    rows = [r for r in plan['titles'] if r['confidence'] != 'unresolved']
    if not rows:
        raise SystemExit('Research the plan before creating the carrier')
    count = max(r['end']-r['start'] for r in rows)+2
    path = Path(args.out).resolve()
    if path.suffix.lower() != '.mov':
        raise SystemExit('Use a .mov output')
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
                    f"color=c=black@0.0:s={int(snap['width'])}x{int(snap['height'])}:r={float(snap['fps'])},format=argb",
                    '-frames:v', str(count), '-c:v', 'qtrle', str(path)], check=True)
    print(f'Created {path}. Keep this file: Resolve references it.')


if __name__ == '__main__':
    main()
