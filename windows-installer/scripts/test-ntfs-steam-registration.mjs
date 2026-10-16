// Execute the actual generated registration expression against a mocked native API.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const python = process.argv[2] || 'python3';
const components = fileURLToPath(new URL('../components/', import.meta.url));
const expression = JSON.parse(execFileSync(python, ['-c',
  'import json; from ntfs_steam import registration_expression; print(json.dumps(registration_expression([{"partuuid":"11111111-2222-3333-4444-555555555555","mount_name":"share-d0-p4"}])))'],
  { cwd: components, encoding: 'utf8' }));
const path = '/var/mnt/steam-libraries/share-d0-p4';

function fixture({ existing = false, mounted = true, badIndex = false, failAdd = false } = {}) {
  const folders = [{ nFolderIndex: 0, strFolderPath: '/home/deck/.local/share/Steam', strUserLabel: 'Home', bIsMounted: true, bIsDefaultFolder: true }];
  if (existing) folders.push({ nFolderIndex: 1, strFolderPath: path, strUserLabel: 'My existing label', bIsMounted: mounted });
  const calls = [];
  const api = {
    async GetInstallFolders() { return folders.map(folder => ({ ...folder })); },
    async AddInstallFolder(selected) {
      calls.push(['add', selected]);
      if (failAdd) throw new Error('Not currently mountable');
      folders.push({ nFolderIndex: 1, strFolderPath: selected, strUserLabel: '', bIsMounted: true });
      return badIndex ? 99 : 1;
    },
    async SetFolderLabel(index, label) {
      calls.push(['label', index, label]);
      folders.find(folder => folder.nFolderIndex === index).strUserLabel = label;
    },
  };
  return { folders, calls, run: () => vm.runInNewContext(expression, { SteamClient: { InstallFolder: api } }, { timeout: 1000 }) };
}

const created = fixture();
assert.equal((await created.run())[0].status, 'added');
assert.equal((await created.run())[0].status, 'existing');
assert.equal(created.calls.filter(call => call[0] === 'add').length, 1);
assert.equal(created.calls.filter(call => call[0] === 'label').length, 1);
assert.equal(created.folders[0].bIsDefaultFolder, true);
assert.equal(created.folders[0].strUserLabel, 'Home');

const existing = fixture({ existing: true });
assert.equal((await existing.run())[0].status, 'existing');
assert.deepEqual(existing.calls, []);
assert.equal(existing.folders[1].strUserLabel, 'My existing label');

const unmounted = fixture({ existing: true, mounted: false });
await assert.rejects(unmounted.run(), /Existing library is not mounted/);
assert.deepEqual(unmounted.calls, []);

const wrongIndex = fixture({ badIndex: true });
await assert.rejects(wrongIndex.run(), /Steam did not mount selected library/);
assert.equal(wrongIndex.calls.some(call => call[0] === 'label'), false);

const unavailable = fixture({ failAdd: true });
await assert.rejects(unavailable.run(), /Not currently mountable/);
assert.equal(unavailable.calls.some(call => call[0] === 'label'), false);

console.log('NTFS_STEAM_NATIVE_REGISTRATION=passed (5 scenarios)');
