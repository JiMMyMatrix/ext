import * as assert from 'assert';
import { applyModelAction, createInitialModel, isSnapshotStale } from '../phase1Model';

suite('Corgi Phase 1 Model', () => {
	test('submit prompt moves the model into clarification state', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentActor, 'intake_shell');
		assert.strictEqual(model.snapshot.currentStage, 'clarification_needed');
		assert.ok(model.activeClarification);
		assert.strictEqual(model.snapshot.pendingPermissionRequest, undefined);
	});

	test('broad analysis prompts offer clarification choices', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze this folder.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.ok(model.activeClarification);
		assert.strictEqual(model.activeClarification?.kind, 'analysis_focus');
		assert.strictEqual(model.activeClarification?.options?.length, 3);
		assert.strictEqual(model.activeClarification?.allowFreeText, true);
	});

	test('governor dialogue requests observe permission before replying', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const model = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'What is the current progress?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(model.snapshot.currentActor, 'orchestration');
		assert.strictEqual(model.activeClarification, undefined);
		assert.ok(model.snapshot.pendingPermissionRequest);
		assert.strictEqual(model.snapshot.pendingPermissionRequest?.recommendedScope, 'observe');
	});

	test('natural progress questions also request observe permission first', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const model = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'what happen?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(model.activeClarification, undefined);
		assert.ok(model.snapshot.pendingPermissionRequest);
		assert.strictEqual(model.snapshot.pendingPermissionRequest?.recommendedScope, 'observe');
	});

	test('submit prompt without semantic route metadata fails closed', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'what happened?',
			request_id: 'req-missing-route',
			now: '2026-04-10T10:00:05.000Z',
		});

		const lastItem = model.feed[model.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.presentation_key, 'error.semantic_route_required');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-missing-route');
		assert.strictEqual(model.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(model.activeClarification, undefined);
	});

	test('observe permission resumes the same governor dialogue request', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const gatedModel = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'hello!',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-hello',
			now: '2026-04-10T10:00:05.000Z',
		});

		const resumedModel = applyModelAction(gatedModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: gatedModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-observe-click',
			now: '2026-04-10T10:00:10.000Z',
		});

		assert.strictEqual(resumedModel.snapshot.permissionScope, 'observe');
		assert.strictEqual(resumedModel.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(resumedModel.snapshot.currentActor, 'governor');
		assert.strictEqual(resumedModel.snapshot.currentStage, 'dialogue_ready');
		const lastItem = resumedModel.feed[resumedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.title, 'Governor response');
		assert.ok(!(lastItem.body ?? '').includes('waiting for a observe permission choice'));
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-hello');
	});

	test('a new governed request keeps its own foreground flow after an observe dialogue completes', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const gatedDialogueModel = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'hello!',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-hello',
			now: '2026-04-10T10:00:05.000Z',
		});
		const observedDialogueModel = applyModelAction(gatedDialogueModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: gatedDialogueModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-observe',
			now: '2026-04-10T10:00:10.000Z',
		});
		const governedPromptModel = applyModelAction(observedDialogueModel, {
			type: 'submit_prompt',
			text: 'analyze the repo',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:15.000Z',
		});
		const clarifiedModel = applyModelAction(governedPromptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: governedPromptModel.activeClarification?.contextRef,
			request_id: 'req-clarify',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(observedDialogueModel.activeForegroundRequestId, undefined);
		assert.strictEqual(governedPromptModel.activeForegroundRequestId, 'req-analyze');
		assert.strictEqual(clarifiedModel.activeForegroundRequestId, 'req-analyze');
		assert.strictEqual(
			clarifiedModel.snapshot.pendingPermissionRequest?.recommendedScope,
			'plan'
		);
		const lastItem = clarifiedModel.feed[clarifiedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'permission_request');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-clarify');
	});

	test('answer clarification produces a permission request', () => {
		const draftModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const acceptedModel = applyModelAction(draftModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: draftModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});

		assert.strictEqual(acceptedModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(acceptedModel.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(acceptedModel.acceptedIntakeSummary, undefined);
		assert.ok(acceptedModel.snapshot.pendingPermissionRequest);
		assert.deepStrictEqual(acceptedModel.snapshot.pendingPermissionRequest.allowedScopes, [
			'plan',
			'execute',
		]);
		assert.strictEqual(acceptedModel.snapshot.permissionScope, 'unset');
		assert.strictEqual(acceptedModel.activeClarification, undefined);
	});

	test('weaker permission scope cannot accept a stronger permission request', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-weaker-submit',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			request_id: 'req-weaker-answer',
			now: '2026-04-10T10:00:10.000Z',
		});
		const rejectedModel = applyModelAction(permissionModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: permissionModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-weaker-observe',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(rejectedModel.snapshot.permissionScope, 'unset');
		assert.ok(rejectedModel.snapshot.pendingPermissionRequest);
		assert.strictEqual(rejectedModel.acceptedIntakeSummary, undefined);
		const lastItem = rejectedModel.feed[rejectedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Permission scope too low');
		assert.strictEqual(lastItem.presentation_key, 'error.permission_scope_too_low');
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
			semantic_route_type: 'governed_work_intent',
			request_id: 'corgi-request:test-provenance',
			now: '2026-04-10T10:00:05.000Z',
		});

		const clarificationItem = model.feed.find(
			(item) => item.type === 'clarification_request'
		);
		assert.ok(clarificationItem);
		assert.strictEqual(clarificationItem?.source_layer, 'intake');
		assert.strictEqual(clarificationItem?.source_actor, 'intake_shell');
		assert.strictEqual(clarificationItem?.turn_type, 'governed_work_intent');
		assert.strictEqual(
			clarificationItem?.in_response_to_request_id,
			'corgi-request:test-provenance'
		);
	});
});
