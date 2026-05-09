import { getExecutionWindowClientScript, type TestWindowAutoStepMode } from './executionWindowClientScript';
import { executionWindowStyles } from './executionWindowStyles';

export type { TestWindowAutoStepMode } from './executionWindowClientScript';

export function getExecutionWindowHtml(
	cspSource: string,
	nonce: string = getNonce(),
	resetPersistedState: boolean = false,
	testAutoStepMode: TestWindowAutoStepMode = 'off'
): string {
	return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; img-src ${cspSource} data:; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"
	/>
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<title>Corgi</title>
	<style>${executionWindowStyles}</style>
</head>
<body>
	<div class="app" id="app" hidden>
		<header class="header">
			<div class="goal-strip" id="headerContent"></div>
		</header>
		<main class="feed" id="feed"></main>
		<footer class="footer">
			<form class="composer" id="composerForm">
				<div class="composer-context" id="composerContext" hidden></div>
				<div class="composer-actions" id="composerActions" hidden></div>
				<textarea
					id="composerInput"
					placeholder="Ask Corgi to work on this repo..."
				></textarea>
				<div class="composer-footer">
					<div class="composer-hint" id="composerHint">Enter to send, Shift+Enter for newline</div>
					<button type="submit" id="composerSubmitButton">Send</button>
				</div>
			</form>
		</footer>
	</div>
	<div class="loading" id="loadingState">Loading Corgi...</div>
	<script nonce="${nonce}">${getExecutionWindowClientScript(resetPersistedState, testAutoStepMode)}</script>
</body>
</html>`;
}

function getNonce() {
	let text = '';
	const possible =
		'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	for (let i = 0; i < 32; i += 1) {
		text += possible.charAt(Math.floor(Math.random() * possible.length));
	}
	return text;
}
