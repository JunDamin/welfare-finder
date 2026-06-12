export const meta = {
  name: 'welfare-eligibility-full-extract',
  description: '전수 1,079건 통합 추출 — 자격(사실만)+서류(출처구분)+동시수급배제. 배치 15×72',
  phases: [{ title: 'Extract', detail: '배치별 Sonnet 에이전트가 Read→추출→Write' }],
}

const N_BATCH = 72
const DIR = 'C:/Users/freed/OneDrive/Documents/2. business/01. writings/26-005 AI Champ 대회 기획서 작성/welfare-finder-site/_ext'

const SHAPE = `{
  "servId": "...",
  "income": { "type": "수급자|차상위|중위소득|소득무관|명시안됨", "median_pct": 65 또는 null, "bound": "이하|이상|구간|null", "raw": "근거 원문(없으면 \\"\\")", "confidence": "high|medium|low" },
  "age": { "min": 0 또는 null, "max": 12 또는 null, "unit": "세|개월|null", "raw": "...", "confidence": "..." },
  "required_categories": [ {"cat": "한부모", "raw": "..."} ],   // OR 조건 — 하나만 맞아도 가능. 명시된 것만
  "documents": [ {"name": "주민등록등본", "kind": "신청서·양식|증명서·확인서|신분·관계|소득·재산|기타", "source": "양식파일|본문언급|양식+본문", "raw": "..."} ],
  "exclusions": [ {"what": "어린이집 보육료", "raw": "..."} ],   // 동시수급 불가(명시된 것만)
  "doc_summary": "준비물 한 줄",
  "eligibility_summary": "대상 한 줄",
  "overall_confidence": "high|medium|low",
  "notes": "애매·AND조건·확인필요"
}`

const RULES = `<역할>대한민국 복지 자격·구비서류를 '검증 가능하게' 구조화하는 추출기. 판정하지 말고 원문에 적힌 사실만 옮긴다.</역할>
<절대원칙>
1. 원문에 없는 것 추론·창작 금지 → null/빈배열/'명시안됨'.
2. 모든 구조값에 근거 원문(raw) 동반. raw 없는 값 만들지 마라.
3. income.median_pct: '중위소득 N%'가 숫자로 또렷할 때만 N. 여러 기준이면 가장 느슨한(높은) 값. '저소득층' 등 모호하면 null + confidence=low. 수급자/차상위(%아님)는 type만 채우고 median_pct=null.
4. required_categories: 'A 또는 B 또는 C'면 모두 나열(OR — 하나만 맞아도 가능). 과배제 금지.
5. documents: 신청서식 파일명(forms)=source"양식파일", 본문 언급("○○증명서 제출/구비")=source"본문언급", 둘 다=source"양식+본문". '○○사업 안내.pdf/지침/계획' 같은 참고자료는 kind="기타" 또는 제외. 없는 서류 추측 금지(잘못 준비 방지). 서류명은 표준 명칭으로 정규화하되 raw 보존.
6. exclusions: '타 법령 중복 시 미지급','○○와 중복 불가' 등 명시된 동시수급 배제만.
7. 자격 텍스트가 빈약하거나 "지원대상 참고" 식이면 추측 말고 비우고 overall_confidence=low, notes에 '원문 정보 부족'.</규칙>`

phase('Extract')
const tasks = []
for (let i = 0; i < N_BATCH; i++) {
  tasks.push(() => agent(
    `${RULES}\n\n작업: 아래 입력 파일을 Read로 읽어라(배열, 항목당 servId/name/target/criteria/content/apply/forms). 각 항목에서 자격·서류를 추출해, 항목별 객체 배열을 만들어 출력 파일에 Write로 저장하라.\n입력: ${DIR}/in/b${i}.json\n출력: ${DIR}/out/b${i}.json  (객체 배열 JSON만, 코드펜스 없이)\n\n각 객체 형태(schema):\n${SHAPE}\n\n끝나면 "OK ${i} <건수>"만 한 줄 보고. 입력의 모든 항목을 빠짐없이 처리하라.`,
    { label: `batch:${i}`, model: 'sonnet' }
  ).then(() => 1).catch(() => 0))
}
const done = await parallel(tasks)
return { batches: done.length, ok: done.filter(Boolean).length }
