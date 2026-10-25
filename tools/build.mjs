import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
const python = existsSync('.venv/Scripts/python.exe') ? '.venv/Scripts/python.exe' : existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python';
for (const [command, args] of [[process.execPath, ['--check','static/app.js']], [python, ['tools/build.py']]]) {
  const result = spawnSync(command, args, {stdio:'inherit'});
  if (result.status !== 0) process.exit(result.status ?? 1);
}
console.log('BUILD OK: JavaScript and Neon TypeScript configuration validated');
