export const executionWindowStyles = String.raw`
		:root {
			color-scheme: light dark;
			--bg: var(--vscode-sideBar-background, var(--vscode-editor-background));
			--panel: var(--vscode-input-background, rgba(127, 127, 127, 0.1));
			--panel-raised: var(--vscode-editorWidget-background, rgba(127, 127, 127, 0.14));
			--line: var(--vscode-sideBar-border, rgba(127, 127, 127, 0.22));
			--line-soft: rgba(127, 127, 127, 0.18);
			--text: var(--vscode-foreground);
			--muted: var(--vscode-descriptionForeground);
			--faint: rgba(127, 127, 127, 0.72);
			--accent: var(--vscode-focusBorder);
			--danger: var(--vscode-errorForeground);
			--success: var(--vscode-testing-iconPassed, #4ec27b);
			--warning: var(--vscode-editorWarning-foreground, #d6b84f);
		}

		* {
			box-sizing: border-box;
		}

		html,
		body {
			height: 100%;
			margin: 0;
			background: var(--bg);
			color: var(--text);
			font-family: var(--vscode-font-family);
			font-size: var(--vscode-font-size, 13px);
		}

		button,
		textarea {
			font: inherit;
		}

		[hidden] {
			display: none !important;
		}

		button {
			border: 1px solid transparent;
			border-radius: 10px;
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			cursor: pointer;
			padding: 6px 10px;
		}

		button.secondary {
			background: var(--vscode-button-secondaryBackground, transparent);
			color: var(--vscode-button-secondaryForeground, var(--text));
			border-color: var(--line);
		}

		button.ghost {
			background: transparent;
			color: var(--muted);
			border-color: transparent;
			padding: 3px 6px;
		}

		button:hover {
			filter: brightness(1.06);
		}

		button:disabled {
			opacity: 0.55;
			cursor: default;
		}

		.app {
			height: 100%;
			display: flex;
			flex-direction: column;
			overflow: hidden;
			background: var(--bg);
		}

		.header {
			flex: 0 0 auto;
			padding: 9px 12px 7px;
			border-bottom: 1px solid var(--line);
		}

		.goal-strip {
			display: grid;
			gap: 3px;
			min-width: 0;
		}

		.goal-main,
		.goal-meta {
			display: flex;
			align-items: center;
			gap: 7px;
			min-width: 0;
		}

		.goal-main {
			color: var(--text);
			font-size: 12px;
			font-weight: 600;
		}

		.goal-title,
		.goal-step {
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

		.goal-label {
			color: var(--muted);
			font-weight: 500;
		}

		.goal-meta {
			color: var(--muted);
			font-size: 11px;
		}

		.goal-separator {
			color: var(--faint);
		}

		.status-dot {
			width: 7px;
			height: 7px;
			border-radius: 50%;
			background: var(--success);
		}

		.status-dot.is-stale {
			background: var(--warning);
		}

		.status-dot.is-ready {
			background: var(--success);
		}

		.header-subline {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
			color: var(--muted);
			font-size: 11px;
		}

		.session-rail {
			flex: 0 0 auto;
			padding: 10px 12px 0;
			display: grid;
			gap: 8px;
		}

		.session-card {
			border: 1px solid var(--line);
			border-radius: 13px;
			background: var(--panel);
			padding: 10px;
			display: grid;
			gap: 8px;
		}

		.session-card.is-collapsed {
			padding: 8px 10px;
			gap: 6px;
		}

		.session-card-header {
			display: flex;
			align-items: flex-start;
			justify-content: space-between;
			gap: 8px;
		}

		.session-label {
			color: var(--muted);
			font-size: 11px;
			font-weight: 600;
			text-transform: uppercase;
			letter-spacing: 0.04em;
		}

		.session-title {
			margin: 2px 0 0;
			font-size: 13px;
			font-weight: 600;
			line-height: 1.4;
		}

		.session-summary {
			color: var(--muted);
			font-size: 12px;
			line-height: 1.45;
		}

		.session-card.is-collapsed .session-summary {
			font-size: 11px;
			line-height: 1.35;
		}

		.session-grid {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: 8px 12px;
		}

		.session-field {
			display: grid;
			gap: 2px;
			min-width: 0;
		}

		.session-field-label {
			color: var(--muted);
			font-size: 11px;
		}

		.session-field-value {
			font-size: 12px;
			line-height: 1.35;
			word-break: break-word;
		}

		.milestone-card {
			border: 1px solid var(--line-soft);
			border-radius: 12px;
			background: var(--panel-raised);
			padding: 9px 10px;
			display: grid;
			gap: 4px;
		}

		.milestone-title {
			font-size: 12px;
			font-weight: 600;
			line-height: 1.4;
		}

		.milestone-body {
			color: var(--muted);
			font-size: 12px;
			line-height: 1.45;
		}

		.pill-row {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
		}

		.pill {
			display: inline-flex;
			align-items: center;
			gap: 5px;
			padding: 3px 8px;
			border-radius: 999px;
			border: 1px solid var(--line);
			background: var(--panel-raised);
			color: var(--muted);
			font-size: 11px;
			line-height: 1.2;
			white-space: nowrap;
		}

		.pill.pill-reveal {
			max-width: min(100%, 28rem);
		}

		.pill-reveal-value {
			display: inline-block;
			max-width: 0;
			overflow: hidden;
			opacity: 0;
			transition: max-width 140ms ease, opacity 140ms ease;
			white-space: nowrap;
		}

		.pill.pill-reveal:hover .pill-reveal-value {
			max-width: 24rem;
			opacity: 1;
		}

		.pill.is-primary {
			color: var(--text);
			border-color: color-mix(in srgb, var(--accent) 50%, var(--line));
		}

		.pill.is-status {
			color: var(--text);
			border-color: color-mix(in srgb, var(--line) 75%, var(--accent));
			background: color-mix(in srgb, var(--panel-raised) 84%, var(--accent) 16%);
		}

		.pill.is-warning {
			color: var(--text);
			border-color: color-mix(in srgb, var(--warning) 45%, var(--line));
		}

		.pill.is-danger {
			color: var(--text);
			border-color: color-mix(in srgb, var(--danger) 45%, var(--line));
		}

		.feed {
			flex: 1 1 auto;
			overflow-y: auto;
			padding: 12px;
			display: flex;
			flex-direction: column;
			gap: 10px;
			min-height: 120px;
		}

		.message {
			display: grid;
			gap: 5px;
			line-height: 1.45;
		}

		.message-label {
			color: var(--muted);
			font-size: 11px;
			font-weight: 600;
		}

			.message-body {
				white-space: pre-wrap;
				word-break: break-word;
			}

			.message-body.is-governor-copy {
				display: grid;
				gap: 8px;
				white-space: normal;
			}

			.message-body.is-governor-copy p {
				margin: 0;
			}

			.message-body.is-governor-copy strong {
				color: var(--text);
				font-weight: 700;
			}

			.inline-code {
				border: 1px solid var(--line);
				border-radius: 5px;
				background: color-mix(in srgb, var(--panel-raised) 85%, transparent);
				padding: 0 4px;
				font-family: var(--vscode-editor-font-family, ui-monospace, SFMono-Regular, Menlo, monospace);
				font-size: 0.92em;
			}

			.message.user {
				align-self: flex-end;
				max-width: 92%;
				border: 1px solid var(--line);
			border-radius: 14px;
			background: var(--panel-raised);
			padding: 9px 10px;
		}

		.message.user .message-label {
			display: none;
		}

		.message.assistant {
			padding: 2px 0;
		}

		.message.error {
			border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
			border-radius: 12px;
			background: color-mix(in srgb, var(--danger) 10%, transparent);
			padding: 9px 10px;
		}

		.message.is-informational {
			color: var(--muted);
		}

		.message.result-summary {
			border: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
			border-radius: 12px;
			background: color-mix(in srgb, var(--panel-raised) 70%, transparent);
			padding: 8px 10px;
		}

		.result-title {
			color: var(--text);
			font-size: 12px;
			font-weight: 700;
		}

		.result-body {
			color: var(--muted);
			font-size: 12px;
			line-height: 1.45;
		}

		.result-details {
			margin-top: 6px;
			color: var(--muted);
			font-size: 12px;
		}

		.result-details summary {
			cursor: pointer;
			user-select: none;
		}

		.result-details .message-body {
			margin-top: 6px;
		}

		.activity-row,
		.activity-overflow-row {
			display: grid;
			grid-template-columns: 18px minmax(0, 1fr);
			gap: 8px;
			align-items: start;
			color: var(--muted);
			padding: 3px 0;
			line-height: 1.45;
		}

		.activity-dot {
			width: 8px;
			height: 8px;
			margin: 6px 0 0 5px;
			border-radius: 50%;
			background: var(--faint);
		}

		.activity-row.is-running .activity-dot,
		.activity-overflow-row.is-running .activity-dot {
			background: var(--accent);
			animation: pulse 1.5s ease-in-out infinite;
		}

		.activity-row.is-completed .activity-dot,
		.activity-overflow-row.is-completed .activity-dot {
			background: var(--success);
		}

		.activity-row.is-failed .activity-dot,
		.activity-row.is-error .activity-dot,
		.activity-overflow-row.is-failed .activity-dot,
		.activity-overflow-row.is-error .activity-dot {
			background: var(--danger);
		}

		.activity-label {
			color: var(--text);
			font-size: 12px;
		}

		.activity-row.is-informational .activity-label,
		.activity-overflow-row.is-informational .activity-label {
			color: var(--muted);
		}

		.activity-summary,
		.feed-empty,
		.composer-hint {
			color: var(--muted);
		}

		.activity-summary {
			margin-top: 2px;
			font-size: 12px;
		}

		.activity-overflow {
			color: var(--muted);
			font-size: 12px;
			padding: 2px 0;
		}

		.activity-overflow summary {
			cursor: pointer;
			user-select: none;
		}

		.activity-overflow-body {
			margin-top: 6px;
			display: grid;
			gap: 4px;
		}

		.inline-actions {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
			align-items: center;
			margin-top: 6px;
		}

		.detail-list {
			margin: 7px 0 0;
			padding-left: 18px;
			color: var(--muted);
			display: grid;
			gap: 4px;
		}

		.detail-list li {
			line-height: 1.4;
		}

		.progress-cluster {
			align-self: flex-start;
			max-width: min(100%, 24rem);
			padding: 8px 10px;
			border-radius: 12px;
			background: transparent;
			border: 1px solid transparent;
		}

		.activity-trace {
			background: transparent;
			box-shadow: none;
			opacity: 0.96;
		}

		.progress-list {
			list-style: none;
			margin: 0;
			padding-left: 0;
			font-size: 12px;
			display: grid;
			gap: 4px;
		}

		.progress-cluster .activity-summary {
			margin-top: 6px;
			font-size: 11px;
		}

		.draft-preview {
			margin-top: 8px;
			max-width: min(100%, 46rem);
			color: var(--text);
			font-size: 13px;
			line-height: 1.55;
			opacity: 0.72;
			white-space: pre-wrap;
		}

		.draft-preview-label {
			margin-bottom: 4px;
			color: var(--muted);
			font-size: 11px;
			letter-spacing: 0.08em;
			text-transform: uppercase;
		}

		.progress-bullet {
			display: grid;
			grid-template-columns: 10px minmax(0, 1fr);
			align-items: center;
			gap: 8px;
			color: var(--muted);
		}

		.progress-bullet::before {
			content: '';
			width: 6px;
			height: 6px;
			border-radius: 50%;
			background: currentColor;
			transform: scale(0.95);
			opacity: 0.75;
		}

		.progress-bullet.is-done {
			color: var(--text);
		}

		.progress-bullet.is-active,
		.progress-bullet.is-waiting {
			color: var(--accent);
		}

		.progress-bullet-text {
			display: inline-block;
		}

		.progress-bullet.is-active .progress-bullet-text,
		.progress-bullet.is-waiting .progress-bullet-text {
			background-image: linear-gradient(
				90deg,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 0%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 38%,
				var(--text) 50%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 62%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 100%
			);
			background-repeat: no-repeat;
			background-size: 360% 100%;
			background-position: 100% 50%;
			-webkit-background-clip: text;
			background-clip: text;
			color: transparent;
			animation: progressShimmer 3.4s cubic-bezier(0.42, 0, 0.2, 1) infinite;
		}

		.progress-bullet.is-failed {
			color: var(--danger);
		}

		.feed-divider {
			display: grid;
			grid-template-columns: 1fr auto 1fr;
			align-items: center;
			gap: 8px;
			margin: 6px 0 2px;
			color: var(--muted);
			font-size: 11px;
			text-transform: uppercase;
			letter-spacing: 0.04em;
		}

		.feed-divider::before,
		.feed-divider::after {
			content: '';
			height: 1px;
			background: var(--line);
		}

		.footer {
			flex: 0 0 auto;
			padding: 10px;
			border-top: 1px solid var(--line);
			background: var(--bg);
		}

		.composer {
			border: 1px solid var(--line);
			border-radius: 14px;
			background: var(--panel);
			display: grid;
			gap: 7px;
			padding: 8px;
		}

		.composer-context {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
		}

		.composer-actions {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
			align-items: center;
		}

		.composer-actions button {
			padding: 4px 9px;
		}

		textarea {
			width: 100%;
			min-height: 42px;
			max-height: 128px;
			resize: vertical;
			border: 0;
			outline: none;
			padding: 0;
			background: transparent;
			color: var(--text);
			line-height: 1.45;
		}

		textarea::placeholder {
			color: var(--muted);
		}

		.composer-footer {
			display: flex;
			justify-content: space-between;
			align-items: center;
			gap: 8px;
		}

		.composer-hint {
			font-size: 11px;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

		#composerSubmitButton {
			min-width: 54px;
			padding: 5px 10px;
			border-radius: 999px;
		}

		.loading {
			height: 100%;
			display: grid;
			place-items: center;
			color: var(--muted);
		}

		@keyframes pulse {
			50% {
				opacity: 0.45;
			}
		}

		@keyframes progressShimmer {
			0% {
				background-position: 100% 50%;
			}
			16% {
				background-position: 100% 50%;
			}
			84% {
				background-position: 0% 50%;
			}
			100% {
				background-position: 0% 50%;
			}
		}

		@media (max-width: 340px) {
			.session-grid {
				grid-template-columns: minmax(0, 1fr);
			}
		}
`;
