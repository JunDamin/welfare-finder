export const meta = {
  name: 'welfare-pdf-guideline-parse-test',
  description: '지침 PDF 텍스트에서 자격·구비서류·금액 정리 — 본문보다 알맹이 많은지 테스트',
  phases: [{ title: 'ParsePDF', detail: 'Sonnet으로 지침 PDF 정리' }],
}

let ITEMS = args
if (typeof ITEMS === 'string') { try { ITEMS = JSON.parse(ITEMS) } catch (e) {} }
if (!Array.isArray(ITEMS)) ITEMS = []

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['servId', 'documents', 'income_hint', 'amount_hint', 'eligibility_hint', 'usable', 'notes'],
  properties: {
    servId: { type: 'string' },
    documents: { type: 'array', items: { type: 'object', additionalProperties: false, required: ['name', 'raw'], properties: { name: { type: 'string' }, raw: { type: 'string' } } } },
    income_hint: { type: 'string' }, amount_hint: { type: 'string' }, eligibility_hint: { type: 'string' },
    usable: { type: 'string', enum: ['유용', '부분', '무관'] }, notes: { type: 'string' },
  },
}

phase('ParsePDF')
const results = await parallel(ITEMS.map((it) => () =>
  agent(
    `<역할>복지 사업안내/지침 PDF에서 추출된 텍스트(노이즈 포함)에서 '${it.name}'의 구비서류·소득기준·금액·대상만 정리. 다른 복지 섞이면 무시, 없으면 비움(추측 금지).</역할>\n<PDF발췌 — ${it.name}>\n${it.text}\n</PDF발췌>\nschema대로. servId="${it.servId}". 발췌가 엉뚱하면 usable="무관".`,
    { label: `pdf:${it.servId}`, schema: SCHEMA, model: 'sonnet' }
  ).then(r => ({ ...r, _name: it.name })).catch(() => null)
))
const clean = results.filter(Boolean)
await agent(`다음 JSON을 Write 도구로 이 경로에 그대로 저장:\n경로: C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_pdfresult.json\n내용:\n${JSON.stringify(clean)}`, { label: 'save' })
return { count: clean.length, usable: clean.filter(x => x.usable === '유용').length, withDocs: clean.filter(x => x.documents.length).length }
