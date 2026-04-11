import * as assert from 'assert';
import {
	buildChatFollowups,
	buildChatMarkdown,
	buildChatResultMetadata,
	resolveChatAction,
} from '../chatParticipant';
import { applyModelAction, createInitialModel } from '../phase1Model';

suite('Codex Chat Participant', () => {
	test('plain prompt becomes clarification answer when intake is asking a question', () => {
		const draftModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});

		const action = resolveChatAction(
			undefined,
			'Keep the normal UI concise.',
			draftModel
		);

		assert.deepStrictEqual(action, {
			type: 'answer_clarification',
			text: 'Keep the normal UI concise.',
		});
	});

	test('approve slash command maps to approve action', () => {
		const model = createInitialModel('2026-04-10T10:00:00.000Z');
		const action = resolveChatAction('approve', '', model);

		assert.deepStrictEqual(action, { type: 'approve' });
	});

	test('followups suggest approval commands when approval is pending', () => {
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

		const followups = buildChatFollowups(buildChatResultMetadata(approvalModel));

		assert.ok(followups.some((followup) => followup.command === 'approve'));
		assert.ok(followups.some((followup) => followup.command === 'hold'));
	});

	test('status followup is offered when there is no pending action', () => {
		const now = new Date().toISOString();
		const followups = buildChatFollowups(
			buildChatResultMetadata(createInitialModel(now))
		);

		assert.ok(followups.some((followup) => followup.command === 'status'));
	});

	test('default reply stays concise without recent activity or transport notes', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			now: '2026-04-10T10:00:05.000Z',
		});

		const markdown = buildChatMarkdown(model);

		assert.ok(markdown.includes('Reply here to continue.'));
		assert.ok(!markdown.includes('Recent activity'));
		assert.ok(!markdown.includes('connection:'));
		assert.ok(!markdown.includes('snapshot: stale'));
	});

	test('status view shows concise readiness and connection details only on demand', () => {
		const readyMarkdown = buildChatMarkdown(createInitialModel(), {
			includeStatus: true,
		});
		assert.ok(readyMarkdown.includes('Ask for a change or follow-up.'));
		assert.ok(readyMarkdown.includes('Ready.'));

		const staleModel = createInitialModel('2026-04-10T10:00:00.000Z');
		staleModel.snapshot.transportState = 'degraded';
		staleModel.snapshot.snapshotFreshness.stale = true;

		const staleMarkdown = buildChatMarkdown(staleModel, {
			includeStatus: true,
		});

		assert.ok(staleMarkdown.includes('Connection is degraded.'));
		assert.ok(staleMarkdown.includes('State may be stale.'));
	});
});
