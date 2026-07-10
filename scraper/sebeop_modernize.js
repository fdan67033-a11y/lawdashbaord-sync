export const meta = {
  name: 'sebeop-modernize',
  description: '세법 기출 카드 46개를 현행 세법(2026)에 맞게 현행화 + 내 해설. 세율·한도 변동 주의(verify 적극).',
  phases: [{ title: '현행화', detail: '파일별 에이전트가 세법 카드를 현행화 JSON으로 저장' }],
}
const SCHEMA = { type:'object', additionalProperties:false,
  required:['file','total','current','amended','obsolete','verify','out_path'],
  properties:{ file:{type:'string'}, total:{type:'number'}, current:{type:'number'},
    amended:{type:'number'}, obsolete:{type:'number'}, verify:{type:'number'},
    obsolete_nos:{type:'array',items:{type:'string'}}, out_path:{type:'string'}, notes:{type:'string'} } }
const PROMPT = "당신은 대한민국 세법 전문가입니다. 아래 기출문제 카드를 읽고 각 문제를 현행 세법(2026년 1월 기준)에 맞게 현행화하세요.\n\n1) Read 도구로 이 절대경로 파일을 읽으세요: <<PATH>>\n입력: { meta, questions:[{no, stem, choices:[{no,text}], answer, explanation}] }. PDF추출로 공백이 빠져 붙어있을 수 있으니 의미를 복원해 읽으세요.\n\n2) 각 문제 처리 (★세법은 매년 개정: 세율·공제·한도·요건·과세표준 구간이 자주 바뀜):\n - 정답 검증 + 당신의 언어로 해설(핵심 조문/세목 포함, 한국어). 남의 해설 베끼지 말 것.\n - law_status: 현행유지 / 개정-개선(세율·한도 등 바뀌면 stem·choices·answer 수정 + change_note에 변경점 명시 예 '세율 20%->24%') / 구법-삭제(폐지 세목·조항은 questions에서 빼고 obsolete_nos에 추가)\n - ★숫자(세율·금액·한도·구간)·연도민감 문항은 현행 수치를 확신 못하면 단정 말고 verify=true. 확신 없으면 현행유지+verify=true.\n\n3) Write 도구로 저장(경로): C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__<원본파일명>\n   내용: { meta:(원본+{updated_by:'workflow-세법',cutoff:'2026-01'}), questions:[{no,topic,stem,choices,answer,my_explanation,law_status,verify,change_note?}], obsolete_nos:[...] } (UTF-8, 한글 그대로)\n\n4) StructuredOutput 요약 반환: file,total,current,amended,obsolete,verify,obsolete_nos,out_path,notes."
function prompt(path){ return PROMPT.replace('<<PATH>>', path) }
const EMBEDDED = [
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2000년도 제1차시험 문제 및 정답__2000년-세법개론(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2004년도 제2차시험 문제__2004년_세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2005년도 제1차시험 문제 및 정답__2005년_세법개론1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2006년도 제1차시험 문제 및 확정정답__2006년_세법개론1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2006년도 제2차시험 문제__2006년도_세법(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2007년도 제1차시험 문제 및 확정정답__2007년+세법개론+제1형(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2007년도 제2차시험 문제__세법(2007년2차).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2008년 제2차시험 문제__세법(2008년제2차).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2008년도 제1차시험 문제 및 확정정답__2008년+세법개론+제1형(확정).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2009년 제2차시험 문제__2009년+2차+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2009년도 제1차시험 문제 및 확정정답__세법개론(1형+최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2010년도 제1차시험 문제 및 확정정답__세법개론(1형)_최종.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2010년도 제2차시험 문제__1.세법문제_2010.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2011년도 제1차시험 문제 및 확정정답__★세법개론_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2011년도 제2차 시험문제__2011년+2차++세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2012년도 제2차 시험문제__2012년+2차+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2012년도 제47회 공인회계사 제1차시험 문제 및 확정정답__☆세법개론_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2013년도 공인회계사 제2차 시험문제__01.세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2013년도 제48회 공인회계사 제1차시험 문제 및 확정정답__2-2+세법개론(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2014년도 공인회계사 제2차 시험문제__(1-1)세법문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2014년도 제49회 공인회계사 제1차시험 문제 및 확정정답__세법개론-1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2015년도 제50회 공인회계사 제1차시험 문제 및 확정정답__2015년-02-2.세법개론+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2015년도 제50회 공인회계사 제2차 시험문제__2015_(1-1)세법+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2016년도 제51회 공인회계사 제1차시험 문제 및 확정정답__02-2.세법+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2016년도 제51회 공인회계사 제2차 시험문제__(1-1)세법+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2017년도 제52회 공인회계사 제2차시험 문제__1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2018년도 제53회 공인회계사 제1차시험 문제 및 확정정답__(2교시)+상법+·+세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2018년도 제53회 공인회계사 제2시험 문제__(2018)+1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2019년도 제54회 공인회계사 제1차시험 문제 및 확정답안__02.+상법_세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2019년도 제54회 공인회계사 제2차시험 문제__(2019)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020년도 제55회 공인회계사 제1차시험 문제 및 가답안__02.+상법+세법개론(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020년도 제55회 공인회계사 제2차시험 문제__(2020)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020학년도 제55회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제(최종)_2020.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2021년도 제56회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2021년도 제56회 공인회계사 제2차시험 문제__(2021)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2022년도 제57회 공인회계사 제1차시험 문제 및 확정답안__02.+상법+세법개론(1형)_문제_2022.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2022년도 제57회 공인회계사 제2차시험 문제__(2022)1-1.+세법.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2023년도 제58회 공인회계사 제1차시험 문제 및 가답안__02.+상법+세법개론(1형)_문제_2023.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2023년도 제58회 공인회계사 제2차시험 문제(PDF 버전)__1-1+세법+문제(2023-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2024년도 제59회 공인회계사 제2차시험 문제__1-1+세법+문제(2024-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2025년도 제60회 공인회계사 제2차시험 문제__1-1+세법+문제(2025-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 제53회 세무사 1차 1교시(재정학, 세법학 개론) A형 문제입니다__시험지(1교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 제53회 세무사 1차 1교시(재정학, 세법학 개론) B형 문제입니다__시험지(1교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\zip_zip__2교시 기업법 세법개론(1형)_문제_2025.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\zip_zip___02.세법(1형)문제_2024.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\zip_zip__세법학 2부.json"
]
phase('현행화')
const items = (Array.isArray(args) && args.length) ? args : EMBEDDED
log('세법 처리 대상: ' + items.length + '파일')
const results = await pipeline(items, (path) => {
  const base = path.split(/[\\/]/).pop()
  return agent(prompt(path), { label:'세법:'+base.slice(0,38), phase:'현행화', schema:SCHEMA, agentType:'general-purpose' })
})
const ok = results.filter(Boolean)
const s = (k)=>ok.reduce((a,r)=>a+(r[k]||0),0)
const summary = { files_done:ok.length, files_failed:results.length-ok.length,
  total_q:s('total'), current:s('current'), amended:s('amended'), obsolete:s('obsolete'), verify:s('verify'),
  obsolete_detail: ok.filter(r=>(r.obsolete||0)>0).map(r=>({file:r.file,nos:r.obsolete_nos})) }
log('세법 현행화: '+JSON.stringify({files:summary.files_done,q:summary.total_q,amended:summary.amended,obsolete:summary.obsolete,verify:summary.verify}))
return summary
