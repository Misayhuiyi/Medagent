import { spawn } from 'child_process';
import { resolve } from 'path';

process.env.UNDERSTAND_ACCESS_TOKEN = 'medagent2026';
process.env.GRAPH_DIR = resolve(import.meta.dirname, '..');

const dashboardDir = resolve(
  import.meta.dirname, '..', '..', '..',
  '.claude', 'plugins', 'understand-anything',
  'understand-anything-plugin', 'packages', 'dashboard'
);

const child = spawn('npx', ['vite', '--host', '127.0.0.1', '--port', '5173'], {
  cwd: dashboardDir,
  stdio: 'inherit',
  env: { ...process.env },
});

process.on('SIGINT', () => { child.kill(); process.exit(); });
child.on('exit', () => process.exit());
