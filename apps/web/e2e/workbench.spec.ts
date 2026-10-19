import { test, expect, type Page } from '@playwright/test';

let workspaceId = '',
  repository = '';
const errors: string[] = [];
const screenshots = process.env.REPOLENS_SCREENSHOT_DIR || '../../data/v6-screenshots';
async function capture(page: Page, name: string) {
  if (name === 'workspace-desktop') {
    const safePath = 'D:\\projects\\example-repository';
    await page.getByRole('textbox', { name: '本地 Git 仓库路径' }).fill(safePath);
    const repositoryPath = page.locator('.repository-item > div > span');
    await repositoryPath.evaluateAll((elements, replacement) => {
      elements.forEach((element) => (element.textContent = replacement));
    }, safePath);
    await expect(repositoryPath).toHaveText(safePath);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${screenshots}/${name}.png`, fullPage: true });
}

async function navigate(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}
async function noOverflow(page: Page) {
  const bounds = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(bounds.scroll).toBeLessThanOrEqual(bounds.width + 1);
}
test.beforeEach(async ({ page }) => {
  page.on('pageerror', (error) => errors.push(error.message));
  const workspaces = await (await page.request.get('/api/workspaces')).json();
  const workspace = workspaces.find((item: { name: string }) => item.name.startsWith('taskboard-'));
  if (workspace) {
    workspaceId = workspace.workspace_id;
    repository = workspace.repository;
  }
});
test.afterEach(async () => {
  expect(errors.splice(0)).toEqual([]);
});

test('new user imports Demo, opens source and sees workspace metadata', async ({ page }) => {
  await navigate(page, '/');
  await page.getByRole('button', { name: '打开演示仓库' }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible();
  const workspaces = await (await page.request.get('/api/workspaces')).json();
  const workspace = workspaces.find((item: { name: string }) => item.name.startsWith('taskboard-'));
  workspaceId = workspace.workspace_id;
  repository = workspace.repository;
  await expect(page.getByRole('heading', { name: '提交记录', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'service.py python', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '代码证据' })).toBeVisible();
  await expect(page.locator('.monaco-editor').first()).toBeVisible();
  await page.getByRole('button', { name: '关闭代码' }).click();
  await noOverflow(page);
  await capture(page, 'workspace-desktop');
});

async function selectWorkspace(page: Page) {
  await page.addInitScript((id) => localStorage.setItem('repolens.workspace.v5', id), workspaceId);
}
test('impact report, Monaco diff, evidence and Markdown/JSON exports', async ({ page }) => {
  await selectWorkspace(page);
  await navigate(page, '/analysis');
  await page.getByRole('button', { name: '分析变更', exact: true }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible();
  await expect(page.locator('.monaco-diff-editor')).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Markdown', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.md$/);
  await page.getByRole('tab', { name: '风险与测试' }).click();
  await expect(page.getByRole('heading', { name: '建议测试', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: '相关证据' }).click();
  await page.locator('.evidence-link').first().click();
  await expect(page.getByRole('dialog', { name: '代码证据' })).toBeVisible();
  await page.getByRole('button', { name: '关闭代码' }).click();
  await noOverflow(page);
  await capture(page, 'analysis-desktop');
});

test('Chinese question and citation open the pinned committed source', async ({ page }) => {
  await selectWorkspace(page);
  await navigate(page, '/search');
  await page
    .getByRole('textbox', { name: '问题', exact: true })
    .fill('TaskService.create_task 如何处理任务标题？');
  await page.getByRole('button', { name: '提问', exact: true }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible();
  await expect(page.getByText('引用已校验', { exact: true })).toBeVisible();
  await page.locator('.claim .evidence-link').first().click();
  await expect(page.getByRole('dialog', { name: '代码证据' })).toBeVisible();
  await expect(page.locator('.monaco-editor').first()).toBeVisible();
  await page.getByRole('button', { name: '关闭代码' }).click();
  await capture(page, 'search-desktop');
});

test('graph nodes, provenance, type filters and path focus work', async ({ page }) => {
  await selectWorkspace(page);
  await navigate(page, '/graph');
  await page.getByRole('textbox', { name: '图起点' }).fill('TaskService.create_task');
  await page.getByRole('button', { name: '构建子图', exact: true }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  expect(await page.locator('.react-flow__edge').count()).toBeGreaterThan(0);
  await page
    .locator('.react-flow__node')
    .filter({ hasText: 'TaskService.create_task' })
    .first()
    .click();
  await expect(page.getByRole('button', { name: '从此节点展开' })).toBeVisible();
  await page.getByLabel('聚焦选中路径').check();
  await page.locator('.graph-detail .evidence-link').click();
  await expect(page.getByRole('dialog', { name: '代码证据' })).toBeVisible();
  await page.getByRole('button', { name: '关闭代码' }).click();
  await noOverflow(page);
  await capture(page, 'graph-desktop');
});

test('Agent shows tool events and retains bounded degradation', async ({ page }) => {
  await selectWorkspace(page);
  await navigate(page, '/traces');
  await page
    .getByRole('textbox', { name: 'Agent 分析问题' })
    .fill('TaskService.create_task 的调用方和相关测试有哪些？');
  await page.getByLabel('最大步数').fill('3');
  await page.getByRole('button', { name: '运行 Agent', exact: true }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible({ timeout: 45000 });
  await expect(page.getByText('已降级', { exact: true })).toBeVisible();
  await expect(page.locator('.trace-event').first()).toBeVisible();
  await page.locator('.trace-event summary').first().click();
  await expect(page.getByRole('heading', { name: '输入', exact: true }).first()).toBeVisible();
  await page.getByLabel('仅失败步骤').check();
  await capture(page, 'trace-desktop');
  const previous = page.locator('.task-item').filter({ hasText: 'import' }).first();
  const target = await previous.getAttribute('href');
  await previous.click();
  await expect(page).toHaveURL(new RegExp(`${target}$`));
  await expect(page.locator('.trace-content h2').first()).toContainText('import');
});

test('frozen evaluation charts, regression cases and unknown quality metrics', async ({ page }) => {
  await navigate(page, '/evaluations');
  await expect(page.locator('.recharts-surface').first()).toBeVisible();
  expect(
    await page
      .locator('.recharts-bar-rectangle path')
      .first()
      .evaluate((element) => (element as SVGGraphicsElement).getBBox().height),
  ).toBeGreaterThan(50);
  await expect(page.getByText('未评测', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button').filter({ hasText: 'flask-graph-v4-010' })).toBeVisible();
  await page.getByLabel('评测集').selectOption('validation-v4');
  await expect(page.getByText('0.6083', { exact: true })).toBeVisible();
  await noOverflow(page);
  await capture(page, 'evaluation-desktop');
});

test('narrow screen navigation, graph and all six routes remain usable', async ({ page }) => {
  await selectWorkspace(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ['/', '/analysis', '/graph', '/search', '/traces', '/evaluations']) {
    await navigate(page, route);
    await noOverflow(page);
    await page.getByRole('button', { name: '打开导航' }).click();
    await expect(page.getByRole('navigation', { name: '主导航' })).toBeVisible();
    await page.getByRole('button', { name: '收起导航' }).click();
  }
  await navigate(page, '/graph');
  await page.getByRole('textbox', { name: '图起点' }).fill('TaskService.create_task');
  await page.getByRole('button', { name: '构建子图', exact: true }).click();
  await expect(page.getByText('任务完成', { exact: true })).toBeVisible();
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  await noOverflow(page);
  await capture(page, 'graph-mobile');
});

test('invalid repository and missing key produce actionable visible failures', async ({ page }) => {
  await navigate(page, '/');
  await page
    .getByRole('textbox', { name: '本地 Git 仓库路径' })
    .fill(repository + '/does-not-exist');
  await page.getByRole('button', { name: '导入仓库', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Repository path does not exist');
  await page.screenshot({ path: `${screenshots}/error-state.png`, fullPage: true });
  await selectWorkspace(page);
  await navigate(page, '/search');
  await page.request.post('/api/settings', { data: { api_key: '' } });
  for (const provider of ['deepseek', 'langchain']) {
    await page.getByRole('button', { name: '模型设置', exact: true }).first().click();
    await page.getByLabel('回答模型').selectOption(provider);
    await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    await page.getByRole('textbox', { name: '问题', exact: true }).fill('TaskService.create_task');
    await page.getByRole('button', { name: '提问', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('API Key');
  }
});
