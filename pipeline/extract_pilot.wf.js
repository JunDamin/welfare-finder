export const meta = {
  name: 'welfare-eligibility-extract-pilot',
  description: '복지 상세 텍스트에서 자격조건을 구조화 추출(시범 9건) — 비대칭 정확도: 배제는 확신할 때만',
  phases: [{ title: 'Extract', detail: 'Sonnet 서브에이전트로 항목별 구조화 추출' }],
}

// 디스크의 표본 파일을 에이전트로 읽어온다(워크플로는 직접 fs 접근 불가)
const SAMPLE_PATH = 'C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_sample40.json'
const raw = await agent(
  `파일을 읽어 그 내용(JSON 배열)만 그대로 반환하라. 설명·코드펜스 없이: ${SAMPLE_PATH}`,
  { label: 'load-sample', schema: { type: 'object', additionalProperties: false, required: ['items'], properties: { items: { type: 'array', items: { type: 'object' } } } } }
)
const ITEMS = raw.items

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['servId', 'income', 'age', 'required_categories', 'documents', 'exclusions', 'apply_methods', 'target_summary', 'overall_confidence', 'notes'],
  properties: {
    servId: { type: 'string' },
    income: {
      type: 'object', additionalProperties: false,
      required: ['type', 'median_pct', 'bound', 'knockout_above_pct', 'raw', 'confidence'],
      properties: {
        type: { type: 'string', enum: ['수급자', '차상위', '중위소득', '소득무관', '명시안됨'] },
        median_pct: { type: ['integer', 'null'] },
        bound: { type: ['string', 'null'], enum: ['이하', '이상', '구간', null] },
        knockout_above_pct: { type: ['integer', 'null'], description: '★배제선: 중위소득 이 %를 명백히 초과하면 무조건 탈락. 숫자로 또렷할 때만. 수급자/차상위처럼 %가 아니면 null' },
        raw: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
      },
    },
    age: {
      type: 'object', additionalProperties: false,
      required: ['min', 'max', 'unit', 'knockout', 'raw', 'confidence'],
      properties: {
        min: { type: ['number', 'null'] }, max: { type: ['number', 'null'] },
        unit: { type: ['string', 'null'], enum: ['세', '개월', null] },
        knockout: { type: 'boolean', description: '★이 연령범위를 벗어나면 무조건 탈락이라 확신할 수 있나(명시 범위 또렷할 때만 true)' },
        raw: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
      },
    },
    required_categories: {
      type: 'array', description: '★OR 조건의 필수 대상 카테고리. 하나만 충족해도 가능. 명시된 것만, 애매하면 빈 배열(과배제 금지)',
      items: { type: 'object', additionalProperties: false, required: ['cat', 'raw'], properties: { cat: { type: 'string' }, raw: { type: 'string' } } },
    },
    documents: {
      type: 'array', description: '원문 언급 구비서류만',
      items: { type: 'object', additionalProperties: false, required: ['name', 'raw'], properties: { name: { type: 'string' }, raw: { type: 'string' } } },
    },
    exclusions: {
      type: 'array', description: '★동시수급 불가·중복금지: 원문에 "타 법령 중복 시 미지급", "○○와 중복 불가" 등 명시된 배제관계만. 없으면 빈 배열',
      items: { type: 'object', additionalProperties: false, required: ['what', 'raw'], properties: { what: { type: 'string', description: '무엇과 동시에 못 받는지(원문 표현)' }, raw: { type: 'string' } } },
    },
    apply_methods: { type: 'array', items: { type: 'string' } },
    target_summary: { type: 'string' },
    overall_confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    notes: { type: 'string', description: '애매·예외·해석필요(배제 못한 이유, AND조건 등)' },
  },
}

const RULES = `<역할>대한민국 복지 자격조건을 '검증 가능하게' 구조화하는 추출기. 판정하지 말고 원문에 적힌 것만 구조로 옮긴다.</역할>
<절대원칙 — 비대칭 정확도>
1. 이 데이터는 '명백히 안 되는 것을 배제'하는 데 쓰인다. 배제(knockout_above_pct, age.knockout, required_categories)는 100% 확신할 때만. 1%라도 애매하면 비우거나 false + notes에 사유. 잘못 포함은 OK, 잘못 배제는 최악.
2. 원문에 없는 것 추론·창작 금지. 없으면 null/빈배열/'명시안됨'.
3. 모든 구조값에 근거 원문(raw)을 붙여라. raw 없는 값 만들지 마라.
4. knockout_above_pct: '중위소득 N% 이하'처럼 상한이 숫자로 또렷할 때만 N. '저소득층' 등 모호하면 null. 수급자/차상위(%아님)도 null.
5. required_categories: 'A 또는 B 또는 C'면 cat을 모두 나열(OR — 하나만 맞아도 가능). 과배제 금지.
6. 소득과 세대특성을 'AND'로 모두 요구하면 notes에 명시.
7. 한 항목에 소득선이 여러 개면(예: 복지급여 65% / 증명서발급 72%) knockout_above_pct는 '가장 느슨한(높은) 값'으로 — 과배제 금지.
8. 자격 텍스트가 빈약하거나 "지원대상 내용 참고" 식이면 추측하지 말고 전부 비우고(null/빈배열) overall_confidence=low, notes에 '원문 정보 부족' 기재.
9. exclusions: '타 법령 중복 시 미지급', '○○와 중복 불가' 등 명시된 동시수급 배제만. 추측 금지.
출력은 schema의 StructuredOutput 도구로만.</규칙>`

phase('Extract')
const results = await parallel(ITEMS.map((it) => () =>
  agent(
    `${RULES}\n\n<항목>\n이름: ${it.name}\nservId: ${it.servId}\n[지원대상]\n${it.target}\n[선정기준]\n${it.criteria}\n[신청방법]\n${(it.apply || []).join(', ')}\n</항목>\n\n위 원문에서만 자격조건을 schema대로 추출하라. servId는 "${it.servId}". apply_methods는 신청방법 그대로.`,
    { label: `extract:${it.servId}`, schema: SCHEMA, model: 'sonnet' }
  ).then(r => ({ ...r, _name: it.name })).catch(() => null)
))

const clean = results.filter(Boolean)
// 결과를 디스크에 저장(에이전트로 write)
await agent(
  `다음 JSON을 그 내용 그대로 이 경로에 파일로 저장하라(Write 도구 사용, 한 글자도 바꾸지 말 것):\n경로: C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_extract40_result.json\n내용:\n${JSON.stringify(clean)}`,
  { label: 'save-result' }
)
return { count: clean.length, lowConf: clean.filter(r => r.overall_confidence === 'low').length }
