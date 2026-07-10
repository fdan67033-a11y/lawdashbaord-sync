export const meta = {
  name: 'verify-2pass-sangse',
  description: '상법·세법 1차 현행화 결과를 Opus로 2차 비판적 재검증(오류 수정).',
  phases: [{ title: '2차검증', detail: '검증 에이전트가 1차 결과를 재점검·수정' }],
}
const SCHEMA = { type:'object', additionalProperties:false,
  required:['file','total','confirmed','corrected','out_path'],
  properties:{ file:{type:'string'}, total:{type:'number'}, confirmed:{type:'number'}, corrected:{type:'number'}, answer_fixed:{type:'number'}, status_changed:{type:'number'}, out_path:{type:'string'}, notes:{type:'string'} } }
const PROMPT = "당신은 대한민국 상법·세법 전문가입니다. 아래는 어떤 에이전트가 1차로 '현행화'한 기출문제 결과 JSON입니다. 이를 **비판적으로 재검증**하세요(2차 패스).\n\n1) Read 도구로 이 1차 결과 파일을 읽으세요: <<PATH>>\n구조: { meta, questions:[{no, topic, stem, choices, answer, my_explanation, law_status, verify, change_note?}], obsolete_nos:[...] }\n\n2) 각 문제를 독립적으로 다시 판단해 1차 결과의 오류를 잡으세요(2026년 1월 현행 기준):\n - 정답(answer)이 맞는가? 틀렸으면 고치고 verify_note에 사유.\n - my_explanation에 사실오류·조문오기·잘못된 현행화가 있는가? 있으면 수정.\n - law_status(현행유지/개정-개선/구법-삭제)가 적절한가? 1차가 놓친 개정/폐지가 있으면 바로잡고, 과도한 구법처리는 되돌림.\n - 숫자(세율·한도)·연도민감 항목은 확신 없으면 verify=true 유지/설정.\n - 각 문제에 verified=true 표시. 1차에서 바뀐 게 있으면 verify_note에 '무엇을 어떻게 고쳤는지', 맞으면 verify_note='확인-수정없음'.\n\n3) Write 도구로 같은 경로(<<PATH>>)에 덮어쓰기 저장. meta에 {verified_by:'opus-2pass', verified_cutoff:'2026-01'} 추가. 구조·필드 유지(questions에 verified, verify_note 추가). UTF-8 한글 그대로.\n\n4) StructuredOutput 요약 반환: file,total,confirmed(수정없음),corrected(수정함),answer_fixed(정답바뀜),status_changed(law_status바뀜),out_path,notes."
function prompt(path){ return PROMPT.replace(/<<PATH>>/g, path) }
const EMBEDDED = [
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__bupmu__2014년 제20회 법무사 상법 기출문제__2014 제20회 법무사 상법 기출문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2000년도 제1차시험 문제 및 정답__2000년-상법(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2005년도 제1차시험 문제 및 정답__2005년_상법1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2006년도 제1차시험 문제 및 확정정답__2006년_상법1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2007년도 제1차시험 문제 및 확정정답__2007년+상법+제1형(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2008년도 제1차시험 문제 및 확정정답__2008년+상법+제1형(확정).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2009년도 제1차시험 문제 및 확정정답__상법문제(1형+최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2010년도 제1차시험 문제 및 확정정답__상법(1형)_최종.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2011년도 제1차시험 문제 및 확정정답__★상법_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2012년도 제47회 공인회계사 제1차시험 문제 및 확정정답__☆상법_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2013년도 제48회 공인회계사 제1차시험 문제 및 확정정답__2-1+상법(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2014년도 제49회 공인회계사 제1차시험 문제 및 확정정답__상법-1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2015년도 제50회 공인회계사 제1차시험 문제 및 확정정답__2015년-02-1.상법+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2016년도 제51회 공인회계사 제1차시험 문제 및 확정정답__02-1.상법+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2017년도 제52회 공인회계사 제1차시험 문제 및 확정정답__02-1.+상법+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2018년도 제53회 공인회계사 제1차시험 문제 및 확정정답__(2교시)+상법+·+세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2019년도 제54회 공인회계사 제1차시험 문제 및 확정답안__02.+상법_세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2020년도 제55회 공인회계사 제1차시험 문제 및 가답안__02.+상법+세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2020학년도 제55회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제(최종)_2020.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2021년도 제56회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2022년도 제57회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제_2022.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2023년도 제58회 공인회계사 제1차시험 문제 및 가답안__02.+상법+세법개론(1형)_문제_2023.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2016년 세무사 1차 2교시(회계학 개론, 상법) A형 문제입니다__회계학개론,상법(2교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2016년 세무사 1차 2교시(회계학 개론, 상법) B형 문제입니다__회계학개론,상법(2교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2017년 세무사 1차 2교시_A형_상법(선택) 문제지입니다__2교시_A형_상법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2017년 세무사 1차 2교시_B형_상법(선택) 문제지입니다__2교시_B형_상법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__web_bupmu__47653_제19회 법무사 1차 상법(1책형) 기출문제_해설_0.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2021년도 제58회 세무사 1차 시험 2교시 A형(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2021년도 제58회 세무사 1차 시험 2교시 B형(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2022년도 제59회 세무사 1차 시험 2교시 문제지 A형(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2023년 제60회 세무사 1차시험 2교시 문제지(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2024년도 제61회 세무사 1차시험 2교시 시험지 원본(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2025년도 제62회 세무사 1차시험 2교시 시험지 원본(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_semu__2026년도 제63회 세무사 1차시험 2교시 시험지 원본(상법).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_zip__2교시 기업법 세법개론(1형)_문제_2025.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_zip___02.상법(1형)문제_2024.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2000년도 제1차시험 문제 및 정답__2000년-세법개론(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2004년도 제2차시험 문제__2004년_세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2005년도 제1차시험 문제 및 정답__2005년_세법개론1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2006년도 제1차시험 문제 및 확정정답__2006년_세법개론1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2006년도 제2차시험 문제__2006년도_세법(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2007년도 제1차시험 문제 및 확정정답__2007년+세법개론+제1형(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2007년도 제2차시험 문제__세법(2007년2차).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2008년 제2차시험 문제__세법(2008년제2차).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2008년도 제1차시험 문제 및 확정정답__2008년+세법개론+제1형(확정).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2009년 제2차시험 문제__2009년+2차+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2009년도 제1차시험 문제 및 확정정답__세법개론(1형+최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2010년도 제1차시험 문제 및 확정정답__세법개론(1형)_최종.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2010년도 제2차시험 문제__1.세법문제_2010.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2011년도 제1차시험 문제 및 확정정답__★세법개론_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2011년도 제2차 시험문제__2011년+2차++세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2012년도 제2차 시험문제__2012년+2차+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2012년도 제47회 공인회계사 제1차시험 문제 및 확정정답__☆세법개론_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2013년도 공인회계사 제2차 시험문제__01.세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2013년도 제48회 공인회계사 제1차시험 문제 및 확정정답__2-2+세법개론(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2014년도 공인회계사 제2차 시험문제__(1-1)세법문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2014년도 제49회 공인회계사 제1차시험 문제 및 확정정답__세법개론-1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2015년도 제50회 공인회계사 제1차시험 문제 및 확정정답__2015년-02-2.세법개론+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2015년도 제50회 공인회계사 제2차 시험문제__2015_(1-1)세법+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2016년도 제51회 공인회계사 제1차시험 문제 및 확정정답__02-2.세법+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2016년도 제51회 공인회계사 제2차 시험문제__(1-1)세법+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2017년도 제52회 공인회계사 제2차시험 문제__1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2018년도 제53회 공인회계사 제2시험 문제__(2018)+1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2019년도 제54회 공인회계사 제2차시험 문제__(2019)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2020년도 제55회 공인회계사 제2차시험 문제__(2020)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2021년도 제56회 공인회계사 제2차시험 문제__(2021)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2022년도 제57회 공인회계사 제2차시험 문제__(2022)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2023년도 제58회 공인회계사 제2차시험 문제(PDF 버전)__1-1+세법+문제(2023-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2024년도 제59회 공인회계사 제2차시험 문제__1-1+세법+문제(2024-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__cpa__2025년도 제60회 공인회계사 제2차시험 문제__1-1+세법+문제(2025-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2016년 제53회 세무사 1차 1교시(재정학, 세법학 개론) A형 문제입니다__시험지(1교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__semu__2016년 제53회 세무사 1차 1교시(재정학, 세법학 개론) B형 문제입니다__시험지(1교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_zip___02.세법(1형)문제_2024.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__zip_zip__세법학 2부.json"
]
phase('2차검증')
const items = (Array.isArray(args) && args.length) ? args : EMBEDDED
log('2차검증 대상: ' + items.length + '파일')
const results = await pipeline(items, (path) => {
  const base = (path.match(/[^\/]+$/) || [path])[0]
  return agent(prompt(path), { label:'검증:'+base.slice(0,36), phase:'2차검증', schema:SCHEMA, agentType:'general-purpose', model:'opus' })
})
const ok=results.filter(Boolean)
const s=(k)=>ok.reduce((a,r)=>a+(r[k]||0),0)
const summary={files_done:ok.length, files_failed:results.length-ok.length, total_q:s('total'), confirmed:s('confirmed'), corrected:s('corrected'), answer_fixed:s('answer_fixed'), status_changed:s('status_changed')}
log('2차검증: '+JSON.stringify(summary))
return summary
