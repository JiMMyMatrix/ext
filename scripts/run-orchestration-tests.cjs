const fs = require('fs');
const { spawnSync } = require('child_process');

function resolvePythonExecutable() {
	if (process.env.CORGI_PYTHON && process.env.CORGI_PYTHON.trim()) {
		return process.env.CORGI_PYTHON.trim();
	}

	if (process.platform === 'darwin') {
		for (const candidate of ['/opt/homebrew/bin/python3', '/usr/local/bin/python3']) {
			if (fs.existsSync(candidate)) {
				return candidate;
			}
		}
	}

	return 'python3';
}

const python = resolvePythonExecutable();
console.log(`[orchestration] using ${python}`);
const result = spawnSync(
	python,
	['-m', 'unittest', 'discover', '-s', 'orchestration/tests', '-p', 'test_*.py'],
	{
		stdio: 'inherit',
	}
);

if (result.error) {
	console.error(result.error.message);
	process.exit(1);
}

process.exit(result.status ?? 1);
