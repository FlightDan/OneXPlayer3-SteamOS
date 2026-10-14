"""Build our minimal compatibility patch from the unmodified TabMaster 2.15.1 ZIP."""
import argparse
import difflib
import json
from pathlib import Path
import zipfile

BASE_VERSION = '2.15.1'
VERSION = '2.15.1+oxp3.1'
ARCHIVE = 'tabmaster-' + VERSION + '.zip'
REPLACEMENTS = (
    ('appAchievementProgressCache.m_achievementProgress.mapCache.size',
     '(appAchievementProgressCache.m_achievementProgress?.mapCache?.size ?? 0)'),
    ('appAchievementProgressCache.m_achievementProgress.mapCache.get(appOverview.appid)',
     'appAchievementProgressCache.m_achievementProgress?.mapCache?.get(appOverview.appid)'),
)


def patch_text(text):
    for original, replacement in REPLACEMENTS:
        if text.count(original) != 1:
            raise RuntimeError('Unexpected TabMaster cache access: ' + original)
        text = text.replace(original, replacement)
    return text


def build(source, destination, patch_directory):
    patch_directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as upstream:
        data = {item.filename: upstream.read(item) for item in upstream.infolist()}
        metadata = json.loads(data['TabMaster/package.json'])
        if metadata['version'] != BASE_VERSION: raise RuntimeError('Unexpected upstream version')
        original = data['TabMaster/dist/index.js'].decode()
        changed = patch_text(original)
        directive = '//# sourceMappingURL=index.js.map'
        if changed.count(directive) != 1: raise RuntimeError('Unexpected upstream source map directive')
        changed = changed.replace(directive, '// Upstream column mappings are not exact on the two locally patched lines.')
        metadata['version'] = VERSION
        metadata['oxp3_compatibility_patch'] = 'Allow absent Steam achievement cache during initialization'
        data['TabMaster/package.json'] = (json.dumps(metadata, indent=2) + '\n').encode()
        data['TabMaster/dist/index.js'] = changed.encode()
        mapping = json.loads(data['TabMaster/dist/index.js.map'])
        sources = {}
        for index, (name, text) in enumerate(zip(mapping['sources'], mapping['sourcesContent'])):
            if name.endswith('/state/TabMasterManager.tsx'):
                before, after = REPLACEMENTS[0]
            elif name.endswith('/components/filters/Filters.tsx'):
                before, after = REPLACEMENTS[1]
            else: continue
            if text.count(before) != 1: raise RuntimeError('Unexpected corresponding source')
            updated = text.replace(before, after)
            relative = 'src/' + name.split('/src/', 1)[1]
            sources[relative] = updated
            mapping['sourcesContent'][index] = updated
            data['TabMaster/oxp3-compat/' + relative] = updated.encode()
            target = patch_directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding='utf-8')
            diff = ''.join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True),
                           fromfile='a/' + relative, tofile='b/' + relative))
            data['TabMaster/oxp3-compat/' + relative + '.patch'] = diff.encode()
        if len(sources) != 2: raise RuntimeError('Missing corresponding source')
        # Keep upstream mappings for source reference only; dropping segments
        # would corrupt subsequent relative source deltas. Disable the runtime
        # directive because columns on the two edited lines have changed.
        data['TabMaster/dist/index.js.map'] = json.dumps(mapping, separators=(',', ':')).encode()
        note = ('OXP3 compatibility patch ' + VERSION + '\n'
                'Base: unmodified TabMaster ' + BASE_VERSION + ' from the official Decky store.\n'
                'Steam may legitimately leave m_achievementProgress undefined.\n'
                'Use size 0 while absent, retain the subscription for later cache initialization,\n'
                'and skip missing entries in achievement-count filters.\n'
                'GetAchievementProgress remains unchanged so Steam can queue cache updates.\n'
                'Corresponding modified TypeScript and unified diffs are included.\n'
                'The source map retains upstream mappings; runtime auto-loading is disabled.\n'
                'Original GPL-3.0/BSD notices are preserved.\n')
        data['TabMaster/oxp3-compat/README.txt'] = note.encode()
        (patch_directory / 'README.txt').write_text(note, encoding='utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for item in upstream.infolist(): output.writestr(item, data.pop(item.filename))
            for name, content in data.items(): output.writestr(name, content)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--patch-directory', type=Path, required=True)
    arguments = parser.parse_args()
    print(build(arguments.source, arguments.destination, arguments.patch_directory))
