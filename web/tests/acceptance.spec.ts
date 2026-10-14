import {test,expect} from '@playwright/test';
import path from 'node:path';
const evidence=path.resolve('../data/qa');
test('findings, graph provenance and exact visual source remain inspectable',async({page})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/findings?q=Planter');
 await page.getByRole('button',{name:/Planter Box Membrane DS-1 /}).click();
 await expect(page.getByRole('heading',{name:'Planter Box Membrane',exact:true})).toBeVisible();
 await expect(page.getByText('Occurrence-specific', {exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:/Author’s reasoning/})).toBeVisible();
 await page.screenshot({path:path.join(evidence,'ui-desktop.png')});
 await page.getByRole('button',{name:'Graph',exact:true}).click();
 await page.getByRole('link',{name:'Open evidence graph'}).click();
 await expect(page.getByText(/Neo4j qualified evidence projection/)).toBeVisible();
 const choices=page.getByLabel('Inspect a relationship');
 const option=await choices.locator('option').nth(1).getAttribute('value');
 await choices.selectOption(option!);
 await expect(page.getByRole('heading',{name:'Qualified relationship'})).toBeVisible();
 await expect(page.getByRole('link',{name:'Source 1 ↗'})).toBeVisible();
 await page.screenshot({path:path.join(evidence,'ui-graph.png')});
 await page.goto('/media?q='+encodeURIComponent('AS 4654.2-2012 Figure 2.17'));
 await page.locator('.media-tile').first().click();
 await expect(page.getByText('AS 4654.2-2012',{exact:true})).toBeVisible();
 await expect(page.getByText('figure 2.17',{exact:true})).toBeVisible();
 await expect(page.getByText('Paragraph ordinal',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Zoom in'}).click();
 await expect(page.getByText('125%',{exact:true})).toBeVisible();
 await page.screenshot({path:path.join(evidence,'ui-figure.png')});
 expect(errors).toEqual([]);
});

test('historical research is saved as sourced partial output with models disabled',async({page})=>{
 await page.goto('/research');
 await page.getByLabel('Research question').fill('planter membrane reasoning remediation');
 await page.getByRole('button',{name:'Start research',exact:true}).click();
 await expect(page).toHaveURL(/\/research\/run_/);
 await expect(page.locator('.answer .status').first()).toHaveText('partial',{timeout:60000});
 await expect(page.getByText(/Automated synthesis and independent model verification unavailable/)).toBeVisible();
 await expect(page.locator('.claim').first()).toBeVisible();
 await page.reload();
 await expect(page.locator('.answer .status').first()).toHaveText('partial');
 await page.getByText('Run trace and pinned versions').click();
 await expect(page.getByText(/Graph: research\/1/)).toBeVisible();
 await page.screenshot({path:path.join(evidence,'ui-research.png')});
});

test('part-specific original/remedial contexts and typed fact interrupt work',async({page})=>{
 await page.goto('/projects');
 const projectName='Synthetic browser QA '+Date.now();
 await page.getByLabel('Project name').fill(projectName);
 await page.getByLabel('Building parts, separated by commas').fill('Apartments, Shop');
 await page.getByRole('button',{name:'Create project'}).click();
 await expect(page).toHaveURL(/\/projects\/project_/);
 const contextValue=await page.getByLabel('Part and work context').locator('option').filter({hasText:'Apartments / original work assessment / v1'}).getAttribute('value');
 await page.getByLabel('Part and work context').selectOption(contextValue!);
 await page.getByLabel('jurisdiction',{exact:true}).fill('TEST');
 await page.getByRole('button',{name:'Save new context version'}).click();
 await expect(page.getByLabel('Part and work context').locator('option').filter({hasText:'Apartments / original work assessment / v2'})).toHaveCount(1);
 await page.goto('/research');
 await page.getByLabel('Research mode').selectOption('current');
 await page.getByLabel('Project',{exact:true}).selectOption({label:projectName});
 await page.getByLabel('Building part').selectOption({label:'Apartments'});
 await page.getByLabel('Research question').fill('planter membrane reasoning');
 await page.getByRole('button',{name:'Start research',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Project evidence needed'})).toBeVisible({timeout:60000});
 await page.getByRole('button',{name:'Continue with declared facts'}).click();
 await expect(page.locator('.answer .status').first()).toHaveText('partial',{timeout:60000});
 await expect(page.getByText(/Applicability unresolved/).first()).toBeVisible();
});

test('synthetic source review creates an audited correction and stale saved research',async({page})=>{
 await page.goto('/review');
 await page.getByRole('button',{name:'Source assertions',exact:true}).click();
 await page.locator('.review-row').first().click();
 await page.getByLabel('Corrected assertion value').fill('Synthetic reviewed extraction value');
 await page.getByLabel('Reason / review note').fill('UI regression check on synthetic data only');
 await page.getByRole('button',{name:'Record review',exact:true}).click();
 await expect(page.getByLabel('Reason / review note')).not.toBeVisible();
 await page.goto('/research');
 await expect(page.getByText(/ · stale/).first()).toBeVisible();
});

test('narrow layout keeps navigation and source controls accessible',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/findings?q=Planter');
 await page.getByRole('button',{name:/Planter Box Membrane DS-1 /}).click();
 await expect(page.getByRole('heading',{name:'Planter Box Membrane',exact:true})).toBeVisible();
 const sizes=await page.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));
 expect(sizes.content).toBeLessThanOrEqual(sizes.viewport+1);
 await page.getByRole('button',{name:'Open navigation'}).click();
 await expect(page.getByRole('link',{name:'Library',exact:true})).toBeVisible();
 await page.screenshot({path:path.join(evidence,'ui-mobile.png')});
});
