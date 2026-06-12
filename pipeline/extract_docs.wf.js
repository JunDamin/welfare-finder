export const meta = {
  name: 'welfare-docs-extract-test',
  description: '서류 전용 추출 테스트 — 양식(forms)+본문 언급 서류를 준비물 목록으로 정리, 출처 구분',
  phases: [{ title: 'ExtractDocs', detail: 'Sonnet으로 항목별 구비서류 정리' }],
}

const SAMPLE_PATH = 'C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_docsample.json'
const raw = await agent(
  `파일을 읽어 그 내용(JSON 배열)만 반환: ${SAMPLE_PATH}`,
  { label: 'load', schema: { type: 'object', additionalProperties: false, required: ['items'], properties: { items: { type: 'array', items: { type: 'object' } } } } }
)
const ITEMS = raw.items

const SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['servId', 'documents', 'doc_summary', 'confidence', 'notes'],
  properties: {
    servId: { type: 'string' },
    documents: {
      type: 'array',
      description: '이 복지 신청에 준비해야 할 서류/양식. 양식파일(forms)과 본문에 언급된 서류를 모두 포함',
      items: {
        type: 'object', additionalProperties: false,
        required: ['name', 'kind', 'source', 'raw'],
        properties: {
          name: { type: 'string', description: '서류명 — 표준적 명칭으로 정규화(예: "주민등록등본", "통장 사본", "○○신청서")' },
          kind: { type: 'string', enum: ['신청서·양식', '증명서·확인서', '신분·관계', '소득·재산', '기타'], description: '서류 성격 분류' },
          source: { type: 'string', enum: ['양식파일', '본문언급', '양식+본문'], description: '어디서 나왔나 — forms 파일명이면 양식파일, 텍스트 언급이면 본문언급' },
          raw: { type: 'string', description: '근거(양식 파일명 또는 본문 문장 그대로)' },
        },
      },
    },
    doc_summary: { type: 'string', description: '준비물 한 줄 안내(사용자 친화적). 예: "신청서 1종 + 소득증빙. 양식은 내려받아 작성"' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    notes: { type: 'string', description: '불확실·추가확인 필요 사항(예: 본문에 서류 언급 없어 양식만)' },
  },
}

const RULES = `<역할>대한민국 복지 신청에 '실제로 준비해야 할 서류'를 정리하는 전문가. 사람들이 이 목록만 보고 한 번에 준비할 수 있어야 한다.</역할>
<원칙>
1. 두 출처를 모두 본다: (a) 신청서식 파일명(forms) → 대개 '○○신청서' 양식, source="양식파일". (b) 선정기준·서비스내용·신청방법 본문에 "○○증명서/등본/계약서를 제출/구비/지참" 류 언급 → source="본문언급".
2. 같은 서류가 양식+본문 양쪽이면 합쳐서 source="양식+본문".
3. 원문에 없는 서류를 추측·창작하지 마라. 흔히 필요할 것 같아도 명시 안 됐으면 넣지 마라(잘못 준비 방지).
4. 서류명은 표준 명칭으로 정규화하되(예: "주민등록 등본" → "주민등록등본"), 원문 근거는 raw에 보존.
5. 파일명이 '○○사업 안내.pdf', '지침.pdf'처럼 '안내/지침' 문서면 그건 준비 서류가 아니라 참고자료 → kind="기타", notes에 '참고자료'로 표시하거나 제외.
6. 서류가 전혀 명시 안 됐으면 documents는 양식파일만, confidence=medium/low, notes에 '본문 서류 언급 없음 — 신청처 확인 권장'.
출력은 schema StructuredOutput으로만.</규칙>`

phase('ExtractDocs')
const results = await parallel(ITEMS.map((it) => () =>
  agent(
    `${RULES}\n\n<항목>\n이름: ${it.name}\nservId: ${it.servId}\n[신청서식 파일명]\n${(it.forms || []).join('\n') || '(없음)'}\n[신청방법]\n${(it.apply_raw || []).join(', ')}\n[선정기준]\n${it.criteria}\n[서비스내용]\n${it.content}\n</항목>\n\n위 원문에서 '준비해야 할 서류'를 schema대로 정리하라. servId="${it.servId}".`,
    { label: `docs:${it.servId}`, schema: SCHEMA, model: 'sonnet' }
  ).then(r => ({ ...r, _name: it.name, _formsN: (it.forms || []).length })).catch(() => null)
))

const clean = results.filter(Boolean)
await agent(
  `다음 JSON을 그대로 이 경로에 Write 도구로 저장(한 글자도 바꾸지 말 것):\n경로: C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_docresult.json\n내용:\n${JSON.stringify(clean)}`,
  { label: 'save' }
)
return { count: clean.length }
