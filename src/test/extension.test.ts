import * as assert from 'assert';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	getArtifactById,
	isSnapshotStale,
} from '../phase1Model';
import { OPEN_EXECUTION_WINDOW_COMMAND } from '../executionWindowPanel';

suite('Execution Window UX', () => {
	test('opens the execution window command without throwing', async () => {
		await assert.doesNotReject(async () => {
			await vscode.commands.executeCommand(OPEN_EXECUTION_WINDOW_COMMAND);
		});
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

		assert.strictEqual(acceptedModel.snapshot.currentActor, 'governor');
		assert.strictEqual(acceptedModel.snapshot.currentStage, 'approval_requested');
		assert.ok(acceptedModel.acceptedIntakeSummary);
		assert.ok(acceptedModel.snapshot.pendingApproval);
		assert.strictEqual(acceptedModel.activeClarification, undefined);
	});

	test('approve adds recent artifacts and activity rows for the feed', () => {
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

		assert.strictEqual(runningModel.snapshot.currentActor, 'executor');
		assert.strictEqual(runningModel.snapshot.currentStage, 'running');
		assert.ok(runningModel.snapshot.recentArtifacts.length >= 2);
		assert.ok(getArtifactById(runningModel, 'artifact-extension'));
		assert.ok(
			runningModel.feed.some(
				(item) => item.activity?.kind === 'read' && item.activity.path
			)
		);
		assert.ok(
			runningModel.feed.some(
				(item) =>
					item.activity?.kind === 'command' && item.activity.command
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
});
