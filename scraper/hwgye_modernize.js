export const meta = {
  name: 'hwgye-modernize',
  description: '회계학 기출 카드를 현행 회계기준(K-IFRS, 2026)에 맞게 현행화 + 내 해설.',
  phases: [{ title: '현행화', detail: '파일별 에이전트가 회계학 카드를 현행화' }],
}
const SCHEMA = { type:'object', additionalProperties:false,
  required:['file','total','current','amended','obsolete','verify','out_path'],
  properties:{ file:{type:'string'}, total:{type:'number'}, current:{type:'number'}, amended:{type:'number'}, obsolete:{type:'number'}, verify:{type:'number'}, obsolete_nos:{type:'array',items:{type:'string'}}, out_path:{type:'string'}, notes:{type:'string'} } }
const PROMPT = "당신은 대한민국 회계학(재무회계·원가관리회계, K-IFRS) 전문가입니다. 아래 기출 카드를 현행 회계기준(2026년 1월, 한국채택국제회계기준 K-IFRS 및 일반기업회계기준)에 맞게 현행화하세요.\n\n1) Read 도구로 이 절대경로 파일을 읽으세요: <<PATH>>\n입력: { meta, questions:[{no, stem, choices:[{no,text}], answer, explanation}] }. PDF추출로 공백이 빠져 붙어있을 수 있으니 의미 복원해 읽으세요. 계산문제는 수치·풀이를 정확히.\n\n2) 각 문제 처리(★회계기준 개정 주의: K-IFRS 도입(2011)·신리스(IFRS16)·신수익(IFRS15)·금융상품(IFRS9) 등으로 옛 기준 문제는 폐지/변경될 수 있음):\n - 정답 검증 + 당신의 언어로 해설(핵심 기준서·계정 포함, 한국어). 남의 해설 베끼지 말 것.\n - law_status: 현행유지 / 개정-개선(기준 변경 시 stem·choices·answer 수정 + change_note에 변경점 예 'K-IFRS 제1116호 도입으로 운용리스 회계처리 변경') / 구법-삭제(폐지된 기준·제도 문항은 questions에서 빼고 obsolete_nos에 추가)\n - 계산문제·기준의존 문항으로 현행 처리에 확신 없으면 단정 말고 verify=true. 확신 없으면 현행유지+verify=true.\n\n3) Write 도구로 저장(경로): C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_updated\\updated__<원본파일명>\n   내용: { meta:(원본+{updated_by:'workflow-회계학',cutoff:'2026-01'}), questions:[{no,topic,stem,choices,answer,my_explanation,law_status,verify,change_note?}], obsolete_nos:[...] } (UTF-8, 한글 그대로)\n\n4) StructuredOutput 요약 반환: file,total,current,amended,obsolete,verify,obsolete_nos,out_path,notes."
function prompt(path){ return PROMPT.replace('<<PATH>>', path) }
const EMBEDDED = [
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2000년도 제1차시험 문제 및 정답__2000년-회계학(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2004년도 제2차시험 문제__2004년_재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2005년도 제1차시험 문제 및 정답__2005년_회계학1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2005년도 제2차시험 문제__2005년_재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2006년도 제1차시험 문제 및 확정정답__2006년_회계학1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2006년도 제2차시험 문제__2006년도_원가회계(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2007년도 제1차시험 문제 및 확정정답__2007년+회계학+제1형(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2007년도 제2차시험 문제__재무회계(2007년2차).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2008년도 제1차시험 문제 및 확정정답__2008년+회계학+제1형(확정).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2009년도 제1차시험 문제 및 확정정답__회계학(제1형+최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2010년도 제1차시험 문제 및 확정정답__회계학(1형)_최종+.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2010년도 제2차시험 문제__1.재무회계문제_2010.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2011년도 제1차시험 문제 및 확정정답__★회계학_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2011년도 제2차 시험문제__2011년+2차++재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2012년도 제2차 시험문제__2012년+2차+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2012년도 제47회 공인회계사 제1차시험 문제 및 확정정답__☆회계학_1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2013년도 공인회계사 제2차 시험문제__05.재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2013년도 제48회 공인회계사 제1차시험 문제 및 확정정답__3-1+회계학(1형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2014년도 공인회계사 제2차 시험문제__(2-2)재무회계문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2014년도 제49회 공인회계사 제1차시험 문제 및 확정정답__회계학-1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2015년도 제50회 공인회계사 제1차시험 문제 및 확정정답__2015년-03.회계학+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2015년도 제50회 공인회계사 제2차 시험문제__2015_(2-2)재무회계+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2016년도 제51회 공인회계사 제1차시험 문제 및 확정정답__03-1.회계학+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2016년도 제51회 공인회계사 제2차 시험문제__(2-2)재무회계+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2017년도 제52회 공인회계사 제1차시험 문제 및 확정정답__03.+회계학+1형.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2017년도 제52회 공인회계사 제2차시험 문제__2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2018년도 제53회 공인회계사 제1차시험 문제 및 확정정답__(3교시)+회계학(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2018년도 제53회 공인회계사 제2시험 문제__(2018)+2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2019년도 제54회 공인회계사 제1차시험 문제 및 확정답안__회계학(2019-1차)+문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2019년도 제54회 공인회계사 제2차시험 문제__(2019)2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020년도 제55회 공인회계사 제1차시험 문제 및 가답안__03.+회계학(1형)_문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020년도 제55회 공인회계사 제2차시험 문제__(2020)2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2020학년도 제55회 공인회계사 제1차시험 문제 및 확정답안__03.+회계학(1형)_문제_2020.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2021년도 제56회 공인회계사 제1차시험 문제 및 확정답안__03.+회계학(1형)_문제(최종).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2021년도 제56회 공인회계사 제2차시험 문제__(2021)2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2022년도 제57회 공인회계사 제1차시험 문제 및 확정답안__03.+회계학(1형)_문제_2022.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2022년도 제57회 공인회계사 제2차시험 문제__(2022)2-2.+재무회계.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2023년도 제58회 공인회계사 제1차시험 문제 및 가답안__03.+회계학(1형)_문제_2023.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2023년도 제58회 공인회계사 제2차시험 문제(PDF 버전)__2-2+재무회계+문제(2023-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2024년도 제59회 공인회계사 제2차시험 문제__2-2+재무회계+문제(2024-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\cpa__2025년도 제60회 공인회계사 제2차시험 문제__2-2+재무회계1+문제(2025-2).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2015년도 제52회 세무사 2차 회계학2부 문제입니다__2교시(회계학2부) 시험문제.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 민법) A형 문제입니다__회계학개론,민법(2교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 민법) B형 문제입니다__회계학개론,민법(2교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 상법) A형 문제입니다__회계학개론,상법(2교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 상법) B형 문제입니다__회계학개론,상법(2교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 행정소송법) A형 문제입니다__회계학개론,행정소송법(2교시 A형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 세무사 1차 2교시(회계학 개론, 행정소송법) B형 문제입니다__회계학개론,행소법(2교시 B형).json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2016년 제53회 세무사 2차시험 (2교시)회계학 2부__(2교시)회계학 2부.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\semu__2017년 제54회 세무사 2차 회계학 2부 문제지입니다__회계학 2부.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\zip_zip__3교시 회계학(1형)_문제_2025.json",
  "C:\\todo_manual_dashboard\\law_dashboard_work\\data\\exams_cards\\zip_zip__회계학 2부.json"
]
phase('현행화')
const items = (Array.isArray(args) && args.length) ? args : EMBEDDED
log('회계학 처리 대상: ' + items.length + '파일')
const results = await pipeline(items, (path) => {
  const base = (path.match(/[^\\/]+$/) || [path])[0]
  return agent(prompt(path), { label:'회계학:'+base.slice(0,36), phase:'현행화', schema:SCHEMA, agentType:'general-purpose', model:'opus' })
})
const ok = results.filter(Boolean)
const s=(k)=>ok.reduce((a,r)=>a+(r[k]||0),0)
const summary={files_done:ok.length, files_failed:results.length-ok.length, total_q:s('total'), current:s('current'), amended:s('amended'), obsolete:s('obsolete'), verify:s('verify'), obsolete_detail:ok.filter(r=>(r.obsolete||0)>0).map(r=>({file:r.file,nos:r.obsolete_nos}))}
log('회계학 현행화: '+JSON.stringify({files:summary.files_done,q:summary.total_q,amended:summary.amended,obsolete:summary.obsolete,verify:summary.verify}))
return summary
