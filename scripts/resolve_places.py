"""Resolve helpers. No networking or automatic landmark identification.

Import these functions through a Resolve MCP script or run this file locally.
The caller supplies a reviewed plan and a persistent transparent video carrier.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path


def _id(obj):
    value = obj.GetUniqueId()
    if not value:
        raise RuntimeError('Resolve did not supply a stable unique ID')
    return str(value)


def snapshot(project):
    t = project.GetCurrentTimeline()
    if not t:
        raise RuntimeError('Open a timeline first')
    tracks = []
    for k in range(1, t.GetTrackCount('video') + 1):
        clips = []
        for c in t.GetItemListInTrack('video', k) or []:
            m = c.GetMediaPoolItem()
            clips.append(dict(id=_id(c), name=c.GetName(),
                              start=int(c.GetStart()), end=int(c.GetEnd()),
                              enabled=bool(c.GetClipEnabled()),
                              media_id=_id(m) if m else None,
                              path=m.GetClipProperty('File Path') if m else '',
                              location=m.GetClipProperty('Location') if m else ''))
        tracks.append(dict(index=k, name=t.GetTrackName('video', k),
                           enabled=bool(t.GetIsTrackEnabled('video', k)), clips=clips))
    return dict(project=project.GetName(), timeline=t.GetName(), timeline_id=_id(t),
                start=int(t.GetStartFrame()), fps=float(t.GetSetting('timelineFrameRate')),
                width=int(t.GetSetting('timelineResolutionWidth')),
                height=int(t.GetSetting('timelineResolutionHeight')), tracks=tracks)


def fingerprint(snap, footage_tracks):
    """Includes clip identity, timing and media identity to detect replacements."""
    selected = [t for t in snap['tracks'] if t['index'] in footage_tracks]
    payload = {k: snap[k] for k in ('project', 'timeline', 'timeline_id', 'start', 'fps', 'width', 'height')}
    payload['tracks'] = selected
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def segments(snap, footage_tracks):
    """Candidate topmost-footage intervals; NOT an alpha/transition compositor."""
    wanted = set(footage_tracks)
    available = {t['index'] for t in snap['tracks']}
    if not wanted or not wanted <= available:
        raise ValueError('Select existing footage track indices explicitly')
    clips = [(t['index'], c) for t in snap['tracks'] if t['index'] in wanted and t['enabled']
             for c in t['clips'] if c['enabled']]
    edges = sorted({v for _, c in clips for v in (c['start'], c['end'])})
    rows = []
    for a, b in zip(edges, edges[1:]):
        active = [(k, c) for k, c in clips if c['start'] <= a and c['end'] >= b]
        if not active:
            continue
        k, c = max(active, key=lambda pair: pair[0])
        if rows and rows[-1]['clip_id'] == c['id'] and rows[-1]['end'] == a:
            rows[-1]['end'] = b
        else:
            rows.append(dict(clip_id=c['id'], track=k, start=a, end=b,
                             source_name=c['name'], cn='', en='', confidence='unresolved',
                             evidence='', sources=[]))
    return rows


def make_plan(snap, footage_tracks):
    return dict(project=snap['project'], timeline=snap['timeline'], timeline_id=snap['timeline_id'],
                footage_tracks=footage_tracks, fingerprint=fingerprint(snap, footage_tracks),
                titles=segments(snap, footage_tracks))


def validate_plan(plan, snap):
    if plan['fingerprint'] != fingerprint(snap, plan['footage_tracks']):
        raise ValueError('Timeline/media changed: regenerate and research the plan')
    candidates = segments(snap, plan['footage_tracks'])
    previous_end = -math.inf
    for r in sorted(plan['titles'], key=lambda x: x['start']):
        if type(r['start']) is not int or type(r['end']) is not int or r['end'] <= r['start']:
            raise ValueError('Title range must contain positive integer frame duration')
        if r['start'] < previous_end:
            raise ValueError('Title ranges overlap')
        previous_end = r['end']
        if not any(c['clip_id'] == r['clip_id'] and c['start'] <= r['start']
                   and r['end'] <= c['end'] for c in candidates):
            raise ValueError('Title is not aligned with the reviewed visible clip')
        if r['confidence'] == 'unresolved':
            continue
        if r['confidence'] not in ('verified', 'regional', 'visual'):
            raise ValueError('Unknown evidence level')
        if not r['cn'].strip() or not r['en'].strip() or r['en'] != r['en'].upper():
            raise ValueError('Supply Chinese and uppercase English titles')
        if not r['evidence'].strip() or not r['sources'] or not all(
                isinstance(u, str) and u.startswith('https://') for u in r['sources']):
            raise ValueError('Research evidence and HTTPS sources are required')
    return [r for r in plan['titles'] if r['confidence'] != 'unresolved']


def capture(project, plan, output_dir):
    """Capture composite midpoint frames; refuse unsupported timecode conversion."""
    snap = snapshot(project)
    if plan['fingerprint'] != fingerprint(snap, plan['footage_tracks']):
        raise ValueError('Timeline changed')
    fps = snap['fps']
    if not fps.is_integer() or fps not in (24, 25, 30, 48, 50, 60):
        raise ValueError('Capture helper supports integer NDF fps only; use a connector for other timecodes')
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    t = project.GetCurrentTimeline()
    old_tc = t.GetCurrentTimecode()
    files = []
    try:
        for i, r in enumerate(plan['titles'], 1):
            f = (r['start'] + r['end']) // 2
            nominal = int(fps)
            seconds, frame = divmod(f, nominal)
            h, rest = divmod(seconds, 3600)
            m, s = divmod(rest, 60)
            path = out / f'shot-{i:03}.png'
            if not t.SetCurrentTimecode(f'{h:02}:{m:02}:{s:02}:{frame:02}'):
                raise RuntimeError('Could not seek timeline')
            if not project.ExportCurrentFrameAsStill(str(path)):
                raise RuntimeError('Could not capture frame')
            files.append(str(path))
    finally:
        t.SetCurrentTimecode(old_tc)
    return files


def apply_titles(resolve, plan, carrier_path, chinese_font, english_font,
                 chinese_style='Medium', english_style='Regular'):
    """Write a fresh title track. Caller must explicitly authorize this operation.

    carrier_path is an alpha MOV at timeline fps/resolution, at least as many
    frames as the longest title. Keep it on disk: Resolve references this file.
    """
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    snap = snapshot(project)
    rows = validate_plan(plan, snap)
    if not rows:
        raise ValueError('No researched titles to apply')
    if not chinese_font or not english_font:
        raise ValueError('Select installed fonts first')
    path = Path(carrier_path).resolve()
    if not path.is_file() or path.suffix.lower() != '.mov':
        raise ValueError('Supply a persistent transparent MOV, not a still image')
    t = project.GetCurrentTimeline()
    for k in range(1, t.GetTrackCount('video') + 1):
        if str(t.GetTrackName('video', k)).startswith('Place Titles ·'):
            raise ValueError('A generated title track exists; inspect/update it instead of duplicating')
    backup = t.DuplicateTimeline(t.GetName() + ' · before place titles · ' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    if not backup or not project.SetCurrentTimeline(t):
        raise RuntimeError('Could not create backup/restore target timeline')
    mp = project.GetMediaPool()
    media = mp.ImportMedia([str(path)])
    if not media:
        raise RuntimeError('Carrier import failed')
    if not t.AddTrack('video'):
        raise RuntimeError('Could not add title track')
    track = t.GetTrackCount('video')
    if not t.SetTrackName('video', track, 'Place Titles · bilingual'):
        raise RuntimeError('Could not name title track')
    items = mp.AppendToTimeline([dict(mediaPoolItem=media[0], startFrame=0,
                                    endFrame=r['end']-r['start'], recordFrame=r['start'],
                                    trackIndex=track, mediaType=1) for r in rows])
    if len(items or []) != len(rows):
        raise RuntimeError(f'Partial placement on V{track}; stop and inspect backup {backup.GetName()}')
    for c, r in zip(items, rows):
        if int(c.GetStart()) != r['start'] or int(c.GetEnd()) != r['end']:
            raise RuntimeError('API end-frame semantics/carrier length differ; inspect and adapt, do not continue')
        comp = c.AddFusionComp()
        if not comp:
            raise RuntimeError('Could not create Fusion composition')
        tools = []
        for text, font, style, size, y in ((r['cn'], chinese_font, chinese_style,
                                          .030 if len(r['cn']) > 10 else .033, .14),
                                         (r['en'], english_font, english_style, .016, .102)):
            tool = comp.AddTool('TextPlus')
            for key, value in dict(StyledText=text, Font=font, Style=style, Size=size,
                                   Center={1:.5, 2:y}, Enabled3=1, Opacity3=.8,
                                   Offset3={1:.025, 2:-.025, 3:0}, SoftnessX3=2, SoftnessY3=2).items():
                tool.SetInput(key, value)
            tools.append(tool)
        merge = comp.AddTool('Merge')
        if not merge.ConnectInput('Background', tools[1]) or not merge.ConnectInput('Foreground', tools[0]):
            raise RuntimeError('Could not connect title nodes')
        outputs = list(comp.GetToolList(False, 'MediaOut').values())
        if not outputs or not outputs[0].ConnectInput('Input', merge):
            raise RuntimeError('Could not connect title output')
        if [tool.GetInput('StyledText') for tool in tools] != [r['cn'], r['en']]:
            raise RuntimeError('Title text readback failed')
    if not pm.SaveProject():
        raise RuntimeError('Project save failed; do not report completion')
    return dict(track=track, titles=len(items), backup=backup.GetName(), timeline=snap['timeline'])


def connect():
    try:
        import DaVinciResolveScript as api
    except ImportError as exc:
        raise RuntimeError('Configure the official Resolve scripting module or use an MCP connector; see README') from exc
    resolve = api.scriptapp('Resolve')
    if not resolve or not resolve.GetProjectManager().GetCurrentProject():
        raise RuntimeError('Open Resolve and a project first')
    return resolve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('inspect')
    scan.add_argument('--tracks', required=True, help='Reviewed footage track indices, e.g. 1,2')
    scan.add_argument('--out', required=True)
    cap = sub.add_parser('capture')
    cap.add_argument('--plan', required=True)
    cap.add_argument('--out', required=True)
    check = sub.add_parser('validate')
    check.add_argument('--plan', required=True)
    write = sub.add_parser('apply')
    write.add_argument('--plan', required=True)
    write.add_argument('--carrier', required=True)
    write.add_argument('--chinese-font', required=True)
    write.add_argument('--english-font', required=True)
    write.add_argument('--apply', action='store_true', help='Actually add the title track; otherwise validate only')
    args = parser.parse_args()
    resolve = connect()
    project = resolve.GetProjectManager().GetCurrentProject()
    if args.command == 'inspect':
        snap = snapshot(project)
        plan = make_plan(snap, [int(k) for k in args.tracks.split(',')])
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / 'snapshot.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(segments=len(plan['titles']), out=str(out))))
    else:
        plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
        if args.command == 'capture':
            print(json.dumps(capture(project, plan, args.out)))
        elif args.command == 'apply' and args.apply:
            print(json.dumps(apply_titles(resolve, plan, args.carrier, args.chinese_font, args.english_font), ensure_ascii=False))
        else:
            print(json.dumps(dict(researched_titles=len(validate_plan(plan, snapshot(project))), mutated=False)))


if __name__ == '__main__':
    main()
