import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';
import * as vm from 'vm';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	getArtifactById,
	isSnapshotStale,
} from '../phase1Model';
import {
	EXECUTION_WINDOW_CONTAINER_ID,
	EXECUTION_WINDOW_VIEW_ID,
	getExecutionWindowHtml,
} from '../executionWindowPanel';

const PACKAGE_JSON_PATH = path.resolve(__dirname, '../../package.json');

function loadPackageJson(): Record<string, unknown> {
	return JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8')) as Record<string, unknown>;
}

suite('Corgi Webview UX', () => {
	test('ships sidebar webview contributions without chat participants or open command', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const activationEvents = manifest.activationEvents as string[];
		const viewsContainers = contributes.viewsContainers as Record<string, unknown>;
		const views = contributes.views as Record<string, unknown>;

		assert.ok(Array.isArray(activationEvents));
		assert.ok(viewsContainers.activitybar);
		assert.ok(views[EXECUTION_WINDOW_CONTAINER_ID]);
		assert.strictEqual(contributes.chatParticipants, undefined);
		assert.strictEqual(contributes.commands, undefined);
		assert.ok(!activationEvents.some((event) => event.startsWith('onChatParticipant:')));
	});

	test('opens the Corgi sidebar view without throwing', async () => {
		await assert.doesNotReject(async () => {
			await vscode.commands.executeCommand(
				`workbench.view.extension.${EXECUTION_WINDOW_CONTAINER_ID}`
			);
			await vscode.commands.executeCommand(`${EXECUTION_WINDOW_VIEW_ID}.focus`);
		});
	});

	test('webview inline script is valid JavaScript', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const scriptMatch = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/);

		assert.ok(scriptMatch, 'Expected the generated webview HTML to contain an inline script.');
		assert.doesNotThrow(() => new vm.Script(scriptMatch?.[1] ?? ''));
	});

	test('submit prompt moves the model into clarification state', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentActor, 'intake_shell');
		assert.strictEqual(model.snapshot.currentStage, 'clarification_needed');
		assert.ok(model.activeClarification);
		assert.strictEqual(model.snapshot.pendingApproval, undefined);
	});

	test('broad analysis prompts offer clarification choices', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze this folder.',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.ok(model.activeClarification);
		assert.strictEqual(model.activeClarification?.kind, 'analysis_focus');
		assert.strictEqual(model.activeClarification?.options?.length, 3);
		assert.strictEqual(model.activeClarification?.allowFreeText, true);
	});

	test('governor dialogue stays read-only by default', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const model = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'What is the current progress?',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, initialModel.snapshot.currentStage);
		assert.strictEqual(model.snapshot.currentActor, initialModel.snapshot.currentActor);
		assert.strictEqual(model.activeClarification, undefined);
		assert.strictEqual(model.snapshot.pendingApproval, undefined);
		assert.ok(model.feed.some((item) => item.type === 'actor_event'));
	});

	test('answer clarification produces accepted intake and approval', () => {
		const draftModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});
		const acceptedModel = applyModelAction(draftModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			now: '2026-04-10T10:00:10.000Z',
		});

		assert.strictEqual(acceptedModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(acceptedModel.snapshot.currentStage, 'ready_for_acceptance');
		assert.strictEqual(acceptedModel.acceptedIntakeSummary, undefined);
		assert.ok(acceptedModel.snapshot.pendingApproval);
		assert.strictEqual(acceptedModel.snapshot.accessMode, 'approval_required');
		assert.strictEqual(acceptedModel.activeClarification, undefined);
	});

	test('approve turns the draft into accepted intake artifacts', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'approve',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(runningModel.snapshot.currentStage, 'intake_accepted');
		assert.ok(runningModel.acceptedIntakeSummary);
		assert.ok(runningModel.snapshot.recentArtifacts.length >= 2);
		assert.ok(getArtifactById(runningModel, 'artifact-orchestration-readme'));
		assert.ok(
			runningModel.feed.some(
				(item) => item.type === 'artifact_reference' && item.artifact.path
			)
		);
	});

	test('full access accepts the draft and marks the session as running', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'full_access',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.accessMode, 'full_access');
		assert.strictEqual(runningModel.snapshot.runState, 'running');
		assert.strictEqual(runningModel.snapshot.currentActor, 'governor');
		assert.strictEqual(runningModel.snapshot.currentStage, 'running');
		assert.ok(runningModel.acceptedIntakeSummary?.body.includes('Full access'));
	});

	test('new prompts supersede a pending approval instead of holding it', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			now: '2026-04-10T10:00:10.000Z',
		});
		const supersededModel = applyModelAction(approvalModel, {
			type: 'submit_prompt',
			text: 'Start over with a quieter transcript.',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.ok(
			supersededModel.feed.some(
				(item) =>
					item.type === 'system_status' &&
					item.title === 'Pending approval superseded'
			)
		);
	});

	test('stale snapshots are detected from freshness metadata', () => {
		const model = createInitialModel('2026-04-10T10:00:00.000Z');

		assert.strictEqual(
			isSnapshotStale(
				model.snapshot.snapshotFreshness,
				Date.parse('2026-04-10T10:00:20.000Z')
			),
			false
		);
		assert.strictEqual(
			isSnapshotStale(
				model.snapshot.snapshotFreshness,
				Date.parse('2026-04-10T10:01:00.000Z')
			),
			true
		);
	});

	test('feed items carry internal provenance metadata', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze this folder.',
			now: '2026-04-10T10:00:05.000Z',
		});

		const clarificationItem = model.feed.find(
			(item) => item.type === 'clarification_request'
		);
		assert.ok(clarificationItem);
		assert.strictEqual(clarificationItem?.source_layer, 'intake');
		assert.strictEqual(clarificationItem?.source_actor, 'intake_shell');
		assert.strictEqual(clarificationItem?.turn_type, 'governed_work_intent');
	});
});
