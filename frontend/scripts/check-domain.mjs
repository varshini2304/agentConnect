import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'
const source = await readFile(new URL('../src/workspace/domain.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } })
const { companyIds, phrases, newConfig, validateConfig, readKnowledgeFile, normalizePolicy, canReviewApproval, parseApiDate, trendPoints, approvalCategories } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
assert.deepEqual(companyIds(' 12, 3,12 '), [12, 3])
for (const invalid of ['0', '-1', '2.5', 'word', '9007199254740993']) assert.throws(() => companyIds(invalid))
assert.deepEqual(phrases('one\n two\n\none'), ['one', 'two'])
const limited = newConfig({ providers: { fake: ['deterministic'] }, limits: { max_agent_messages: 1, cooldown_seconds: 90 } })
assert.equal(limited.limits.max_agent_messages, 1)
assert.equal(limited.limits.cooldown_seconds, 90)
const expanded = newConfig({ providers: { fake: ['deterministic'] }, limits: { max_agent_messages: 10, max_conversation_messages: 100, cooldown_seconds: 0 } })
for (const field of ['name', 'description', 'role', 'domain', 'purpose']) expanded[field] = field
assert.equal(validateConfig(expanded), null)
expanded.limits.cooldown_seconds = 0.1
expanded.limits.timeout_seconds = 29.99
assert.equal(validateConfig(expanded), null)
const config = newConfig({ providers: { gemini: [], fake: ['deterministic'] }, limits: {} })
assert.equal(config.provider, 'fake')
assert.equal(config.model, 'deterministic')
assert.match(validateConfig(config), /Complete/)
for (const field of ['name', 'description', 'role', 'domain', 'purpose']) config[field] = field
assert.equal(validateConfig(config), null)
config.limits.max_agent_messages = Number.NaN
assert.match(validateConfig(config), /runtime limit/)
config.limits.max_agent_messages = 101
assert.match(validateConfig(config), /runtime limit/)
config.limits.max_agent_messages = 3
config.max_output_tokens = 63
assert.match(validateConfig(config), /tokens/)
assert.equal(await readKnowledgeFile({ name: 'notes.md', size: 3, text: async () => 'abc' }), 'abc')
await assert.rejects(() => readKnowledgeFile({ name: 'notes.exe', size: 3 }))
await assert.rejects(() => readKnowledgeFile({ name: 'notes.txt', size: 102401 }))
await assert.rejects(() => readKnowledgeFile({ name: 'notes.txt', size: 1, text: async () => '\u0000' }))
console.log('Workspace domain checks passed')
const accessSource = await readFile(new URL('../src/workspace/access.ts', import.meta.url), 'utf8')
const accessCode = ts.transpileModule(accessSource, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 } }).outputText
const { hasPermission, selectedCompany, csrfCookie, canChangeOwner } = await import(`data:text/javascript;base64,${Buffer.from(accessCode).toString('base64')}`)
assert.equal(hasPermission({ status: 'active', permissions: ['posts.read'] }, 'posts.read'), true)
assert.equal(hasPermission({ status: 'active', permissions: ['posts.read'] }, 'posts.publish'), false)
assert.equal(hasPermission({ status: 'suspended', permissions: ['posts.publish'] }, 'posts.publish'), false)
assert.equal(hasPermission(null, 'company.read'), false)
assert.equal(selectedCompany({ selected_company_id: 2, companies: [{ id: 1, status: 'active' }, { id: 2, status: 'active' }] }).id, 2)
assert.equal(selectedCompany({ selected_company_id: 3, companies: [{ id: 1, status: 'active' }] }), undefined)
assert.equal(csrfCookie('other=secret; agentconnect_csrf=a%2Bb'), 'a+b')
assert.equal(csrfCookie('agentconnect_csrf=dev; __Host-agentconnect_csrf=secure'), 'secure')
assert.equal(csrfCookie('session=private'), null)
assert.equal(csrfCookie('agentconnect_csrf=%ZZ'), null)
assert.equal(canChangeOwner('admin', 'owner'), false)
assert.equal(canChangeOwner('admin', 'viewer', 'owner'), false)
assert.equal(canChangeOwner('owner', 'owner', 'viewer'), true)
console.log('Session and permission checks passed')
const scope = (await import(`data:text/javascript;base64,${Buffer.from(accessCode).toString('base64')}`)).companyScopeFor
assert.equal(scope('/agents', 7), 7)
assert.equal(scope('/company-invitations/12/revoke', 7), 7)
for (const path of ['/auth/login', '/auth/workspace', '/account', '/account?x=1', '/company-invitations/preview?token=secret', '/company-invitations/accept']) assert.equal(scope(path, 7), null)
for (const invalid of [null, 0, -1, 1.5, Number.NaN]) assert.equal(scope('/agents', invalid), null)
console.log('Company request scope checks passed')

assert.equal(approvalCategories.length, 7)
const governance = normalizePolicy({ allow_replies: false, daily_execution_budget: 25, limits: { cooldown_seconds: 90 } })
assert.equal(governance.allow_replies, false)
assert.equal(governance.allow_discovery, true)
assert.equal(governance.daily_execution_budget, 25)
assert.equal(governance.limits.cooldown_seconds, 90)
assert.equal(governance.limits.max_agent_messages, 3)
assert.equal(newConfig({ providers: { fake: ['deterministic'] }, limits: {} }).allow_initiation, true)
assert.equal(canReviewApproval('pending', '2026-12-01T00:00:00Z', Date.parse('2026-11-01T00:00:00Z')), true)
assert.equal(canReviewApproval('pending', '2026-11-01T00:00:00Z', Date.parse('2026-11-01T00:00:00Z')), false)
assert.equal(canReviewApproval('executed', '2026-12-01T00:00:00Z', Date.parse('2026-11-01T00:00:00Z')), false)
assert.equal(canReviewApproval('pending', 'invalid'), false)
assert.equal(trendPoints([], 'runs'), '')
assert.equal(trendPoints([{ date: '2026-11-01', runs: 0 }], 'runs'), '50,100')
assert.equal(trendPoints([{ date: '2026-11-01', runs: 1 }, { date: '2026-11-02', runs: 2 }], 'runs'), '0,55 100,10')
console.log('Governance, approval expiry and analytics checks passed')

const previousZone = process.env.TZ
process.env.TZ = 'Asia/Kolkata'
assert.equal(canReviewApproval('pending', '2026-11-01T02:00:00', Date.parse('2026-11-01T00:00:00Z')), true)
assert.equal(parseApiDate('2026-11-01T00:00:00'), Date.parse('2026-11-01T00:00:00Z'))
assert.equal(parseApiDate('2026-11-01T05:30:00+05:30'), Date.parse('2026-11-01T00:00:00Z'))
if (previousZone === undefined) delete process.env.TZ
else process.env.TZ = previousZone
console.log('UTC timestamp and approval timezone checks passed')
