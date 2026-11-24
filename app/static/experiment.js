import {request, element, pretty} from './client.js';

const labels = {
  CONTINUE: '继续放量',
  OBSERVE: '继续观察',
  ROLLBACK: '回滚',
  BLOCKED: '阻断发布',
};
const gateText = {
  NOT_MATURED: '观察窗未满',
  ARM_MISSING: '缺少对照臂',
  PERIOD_MISMATCH: '同周期对照不完整',
  SAMPLE_INSUFFICIENT: '样本不足',
  INTEGRITY: '数据完整性未通过',
};
const issueText = {
  DUPLICATE_SOURCE: '重复来源',
  CROSS_GROUP_OVERLAP: '跨组重叠',
  UNMATCHED_REFUND: '退款无对应转化',
  REFUND_ARM_MISMATCH: '退款与转化实验臂不一致',
  REFUND_EXCEEDS_GROSS: '退款超过毛额',
  ISOLATED_ROW: '隔离行',
};
const CENTS = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 0});

const form = document.querySelector('#exp-source');
const file = document.querySelector('#exp-file');
const profile = document.querySelector('#exp-profile');
const asof = document.querySelector('#exp-asof');
const batchField = document.querySelector('#exp-batch');
const actions = document.querySelector('#exp-actions');
const notice = document.querySelector('#exp-notice');

let state = {batch: null, selected: null, busy: false};

function source() {
  const data = new FormData();
  if (file.files.length) data.append('file', file.files[0]);
  else data.append('sample', profile.value);
  if (asof.value !== '') data.append('as_of', asof.value);
  if (batchField.value.trim()) data.append('batch', batchField.value.trim());
  return data;
}

function announce(text, failure = false) {
  notice.textContent = text;
  notice.dataset.failure = String(failure);
}

function badge(status) {
  return element('span', labels[status] || status, {
    class: 'badge', 'data-result': status, title: status,
  });
}

function money(cents) {
  return CENTS.format(cents) + ' 分';
}

function report() {
  return state.batch?.report;
}

function draw() {
  const data = report();
  if (!data) return;
  const counts = data.balance;
  for (const key of ['groups', 'continue', 'observe', 'rollback']) {
    document.querySelector(`[data-metric="${key}"]`).textContent = counts[key] ?? 0;
  }
  document.querySelector('#exp-batch-state').textContent =
    `${state.batch.id.slice(0, 10)} · r${state.batch.revision}` +
    (state.batch.published ? ' · 已发布' : '');
  document.querySelector('#exp-verdict').textContent = verdict(data);
  document.querySelector('#exp-verdict').dataset.result = data.decision.status;
  drawRows(data);
  drawIncrement(data);
  drawVersions();
  actions.hidden = false;
  document.querySelector('#exp-status').textContent =
    `${state.batch.status} · ${state.batch.reason} · r${state.batch.revision}`;
  document.querySelector('#exp-publish').disabled =
    !data.balance.publishable || state.batch.published;
  document.querySelector('#exp-rollback').disabled =
    (state.batch.versions?.length ?? 0) < 2;
  document.querySelector('#exp-evidence').href =
    `/api/experiments/${state.batch.id}/evidence`;
}

function verdict(data) {
  const ready = data.balance.releasable;
  const base = `整批：${labels[data.decision.status] || data.decision.status}`;
  if (ready) return `${base} · 同周期对照完整、退款净额齐备，可发布`;
  if (data.decision.status === 'BLOCKED') return `${base} · 存在待处理记录，禁止发布`;
  return `${base} · 存在未成熟或对照不完整的组，暂不放量`;
}

function drawRows(data) {
  const table = document.querySelector('#exp-rows');
  table.replaceChildren();
  const head = element('tr');
  head.append(
    ...['活动组', '判定', '门槛', '增量(分)', '处理净额', '对照净额', '记录键'].map(
      title => element('th', title, {scope: 'col'})
    )
  );
  const body = table.createTBody();
  for (const group of data.groups) {
    const tr = body.insertRow();
    const button = element('button', group.group, {
      type: 'button', 'data-group': group.group,
      'aria-pressed': String(group.group === state.selected),
    });
    tr.insertCell().append(button);
    tr.insertCell().append(badge(group.decision));
    tr.insertCell().textContent = group.gates.map(g => gateText[g] || g).join('、') || '—';
    tr.insertCell().textContent = money(group.measure.lift_cents);
    tr.insertCell().textContent = money(group.arms.treatment.net_cents);
    tr.insertCell().textContent = money(group.arms.control.net_cents);
    tr.insertCell().textContent = group.integrity.record_keys.join('、') || '—';
  }
  table.createTHead().append(head);
}

function drawIncrement(data) {
  const target = document.querySelector('#exp-visual');
  target.replaceChildren();
  const group = data.groups.find(item => item.group === state.selected);
  if (!group) return;
  const width = max => Math.max(2, Math.min(100, 100 * Math.abs(group.measure[max]) / scale(data)));
  for (const [name, text] of [['treatment', '处理净额'], ['control', '对照净额']]) {
    const bar = element('div', undefined, {class: 'mark-piece'});
    bar.style.setProperty('--part', `${width(`${name}_net_cents`)}%`);
    bar.append(element('span', `${text} ${money(group.measure[`${name}_net_cents`])}`));
    target.append(bar);
  }
  const lift = group.measure.lift_cents;
  target.append(element(
    'p', `${lift >= 0 ? '正' : '负'}增量 ${money(lift)} · ${group.reason}`, {
      class: 'badge', 'data-result': group.decision,
    }
  ));
}

function scale(data) {
  return Math.max(1, ...data.groups.flatMap(group => [
    Math.abs(group.measure.treatment_net_cents),
    Math.abs(group.measure.control_net_cents),
  ]));
}

function drawVersions() {
  const target = document.querySelector('#exp-versions');
  target.replaceChildren();
  for (const version of state.batch.versions || []) {
    const item = element('li');
    item.append(
      element('button', `r${version.revision}${version.active ? ' · 生效' : ''}`, {
        type: 'button', 'data-version': version.revision,
        'aria-pressed': String(version.active),
      }),
      badge(version.decision)
    );
    target.append(item);
  }
}

function drawDetail(group) {
  document.querySelector('#exp-detail-title').textContent = `组 ${group.group}`;
  const issues = group.integrity.issues.map(issue => ({
    原因: issueText[issue.code] || issue.code,
    记录键: issue.record_keys,
    ...(issue.source ? {来源: issue.source} : {}),
  }));
  document.querySelector('#exp-detail').textContent = pretty({
    判定: group.decision,
    理由: group.reason,
    门槛: group.gates,
    成熟: group.maturity,
    对照: group.control,
    增量: group.measure,
    记录键: group.integrity.record_keys,
    问题: issues,
  });
}

async function perform(action) {
  if (state.busy) return;
  state.busy = true;
  document.body.setAttribute('aria-busy', 'true');
  announce('处理中…');
  try { await action(); }
  catch (error) { announce(error.message, true); }
  finally { state.busy = false; document.body.removeAttribute('aria-busy'); }
}

async function loadHistory() {
  const data = await request('/api/experiments');
  const target = document.querySelector('#exp-history');
  target.replaceChildren();
  for (const run of data.items) {
    const item = element('li');
    item.append(element('button', run.id.slice(0, 10), {
      type: 'button', 'data-batch': run.id,
      'aria-pressed': String(run.id === state.batch?.id),
    }));
    target.append(item);
  }
  if (!data.items.length) target.append(element('li', '尚无判定批次'));
}

async function show(batch) {
  state.batch = batch;
  state.selected = batch.report.groups[0]?.group ?? null;
  batchField.value = batch.id;
  draw();
  if (state.selected) drawDetail(batch.report.groups[0]);
  await loadHistory();
}

form.addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const result = await request('/api/experiments', {method: 'POST', body: source()});
    await show(result);
    announce('判定单已更新');
  });
});

document.querySelector('#exp-rows').addEventListener('click', event => {
  const button = event.target.closest('[data-group]');
  if (!button) return;
  state.selected = button.dataset.group;
  draw();
  drawDetail(report().groups.find(group => group.group === state.selected));
  document.querySelector(`[data-group="${CSS.escape(state.selected)}"]`).focus();
});

document.querySelector('#exp-versions').addEventListener('click', event => {
  const button = event.target.closest('[data-version]');
  if (!button) return;
  perform(async () => {
    const detail = await request(`/api/experiments/${state.batch.id}`);
    const version = detail.versions.find(v => v.revision === Number(button.dataset.version));
    state.batch = {...state.batch, revision: version.revision,
      status: version.decision, reason: version.reason, report: version.report,
      versions: detail.versions};
    state.selected = version.report.groups[0]?.group ?? null;
    draw();
    if (state.selected) drawDetail(version.report.groups[0]);
    announce(`正在查看历史版本 r${version.revision}`);
  });
});

document.querySelector('#exp-history').addEventListener('click', event => {
  const button = event.target.closest('[data-batch]');
  if (!button) return;
  perform(async () => {
    const detail = await request(`/api/experiments/${button.dataset.batch}`);
    await show(detail);
    announce('已载入判定批次');
  });
});

actions.addEventListener('submit', event => {
  event.preventDefault();
  perform(async () => {
    const note = document.querySelector('#exp-note').value;
    const result = await request(`/api/experiments/${state.batch.id}/publish`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({note}),
    });
    await show(result);
    announce('判定单已发布');
  });
});

document.querySelector('#exp-rollback').addEventListener('click', () => {
  perform(async () => {
    const result = await request(`/api/experiments/${state.batch.id}/rollback`, {
      method: 'POST',
    });
    await show(result);
    announce(`已原子回滚到 r${result.revision}`);
  });
});

file.addEventListener('change', () => {
  document.querySelector('#exp-file-name').textContent = file.files[0]?.name || '';
});
profile.addEventListener('change', () => { file.value = ''; document.querySelector('#exp-file-name').textContent = ''; });

perform(async () => {
  const result = await request('/api/experiments', {method: 'POST', body: source()});
  await show(result);
  announce('已载入判定样例');
});
