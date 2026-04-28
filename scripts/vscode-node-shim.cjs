const Module = require('module');
const path = require('path');

const originalLoad = Module._load;

class Uri {
	constructor(fsPath) {
		this.fsPath = fsPath;
		this.path = fsPath;
		this.scheme = 'file';
	}

	static file(fsPath) {
		return new Uri(path.resolve(fsPath));
	}

	static joinPath(base, ...segments) {
		return new Uri(path.join(base.fsPath, ...segments));
	}

	toString() {
		return this.fsPath;
	}
}

class Disposable {
	constructor(callOnDispose = () => undefined) {
		this.callOnDispose = callOnDispose;
	}

	dispose() {
		this.callOnDispose();
	}
}

const vscodeShim = {
	commands: {
		executeCommand: async () => undefined,
	},
	Disposable,
	env: {
		clipboard: {
			writeText: async () => undefined,
		},
	},
	ExtensionMode: {
		Production: 1,
		Development: 2,
		Test: 3,
	},
	Uri,
	ViewColumn: {
		Beside: -2,
	},
	window: {
		registerWebviewViewProvider: () => new Disposable(),
		setStatusBarMessage: () => new Disposable(),
		showTextDocument: async () => undefined,
	},
	workspace: {
		fs: {
			stat: async () => ({ ctime: 0, mtime: 0, size: 0, type: 0 }),
		},
		workspaceFolders: undefined,
	},
};

Module._load = function loadWithVscodeShim(request, parent, isMain) {
	if (request === 'vscode') {
		return vscodeShim;
	}
	return originalLoad.call(this, request, parent, isMain);
};
