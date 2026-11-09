import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './dashboard.css'

type Evidence = { id: string; title: string; url: string; kind: string; period: string; retrieved_at: string; claim: string }
type Product = { name: string; version: string; group: string; description: string; packaging: string; note: string }
type Annual = { year: number; import_usd: number | null; yoy_pct: number | null; source_url: string; retrieved_at: string; is_reported: boolean; is_aggregate: boolean; weight_estimated: boolean }
type Missing = { item: string; needed: string; provider: string; condition: string; basis: string; url?: string }
type Country = { reporter_code: number; name: string; english: string; flag: string; status: string; scope_warning: string; signal: string; signal_kind: string; signal_sources: string[]; hypothesis: string; counter: string; opportunity_type: string; missing: Missing[]; annual: Annual[]; quantitative: { cagr_pct: number | null; complete: boolean } }
type Run = { id: string; created_at: string; product: Product; countries: Country[]; evidence: Evidence[]; limitations: string[] }
type History = { id: string; created_at: string; product_version: string }

async function api<T>(path: string, method = 'GET'): Promise<T> {
  const response = await fetch(`/api${path}`, { method })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `요청을 완료하지 못했습니다 (${response.status}). 서버 실행 상태를 확인하세요.`)
  }
  return response.json()
}
const money = (value: number | null) => value === null ? '미확인' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)
const percent = (value: number | null) => value === null ? '계산 보류' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const date = (value: string) => new Date(value).toLocaleString('ko-KR')

function Sources({ items }: { items: Evidence[] }) {
  return <div className="sources">{items.map(item => <div className="source" key={item.id}>
    <a href={item.url} target="_blank" rel="noreferrer">{item.title} ↗</a>
    <small>{item.kind} · {item.period} · 조회 {item.retrieved_at.slice(0, 10)}</small>
    <p>{item.claim}</p>
  </div>)}</div>
}

function CountryCard({ country: c, evidence }: { country: Country; evidence: Evidence[] }) {
  const [view, setView] = useState<'market' | 'gaps'>('market')
  const latest = c.annual.at(-1)
  return <article className="country-card">
    <header className="country-head">
      <div className={`country-symbol ${c.flag.toLowerCase()}`} aria-hidden="true">{c.flag}</div>
      <div><small>{c.english}</small><h3>{c.name}</h3></div>
      <span className="badge amber">{c.status}</span>
    </header>
    <p className="opportunity">{c.opportunity_type} · 순위 미산정</p>
    <div className="tab-list" role="group" aria-label={`${c.name} 정보 선택`}>
      <button aria-pressed={view === 'market'} onClick={() => setView('market')}>시장과 제품 연결</button>
      <button aria-pressed={view === 'gaps'} onClick={() => setView('gaps')}>추가 확인 {c.missing.length}</button>
    </div>
    {view === 'market' ? <>
      <div className="metric-label">2024 수입액 <span>HS 190531 · 명목 USD</span></div>
      <div className="metric">{money(latest?.import_usd ?? null)}</div>
      <p className="metric-note">2022–2024 CAGR <strong>{percent(c.quantitative.cagr_pct)}</strong><span>검토용 계산값</span></p>
      <div className="scope-note"><span aria-hidden="true">ⓘ</span> {c.scope_warning}</div>
      <details className="trade-details"><summary>연도별 수입액과 원본 보기</summary>
        <table><caption className="sr-only">{c.name} HS190531 연도별 수입</caption><thead><tr><th>연도</th><th>수입액 (USD)</th><th>전년 대비</th></tr></thead>
          <tbody>{c.annual.map(row => <tr key={row.year}><th><a href={row.source_url} target="_blank" rel="noreferrer">{row.year} ↗</a></th><td>{money(row.import_usd)}</td><td>{percent(row.yoy_pct)}</td></tr>)}</tbody></table>
        <p>2026-11-05 보관 응답 재사용 · H6 · 집계 응답 · 국가 원통계 대조 필요. 수입액은 기업 매출이나 실제 소비량이 아닙니다.</p>
      </details>
      <section className="card-section"><div className="eyebrow">소비·시장 신호 <span>{c.signal_kind}</span></div><p>{c.signal}</p></section>
      <section className="card-section hypothesis"><div className="eyebrow">제품 연결 가설</div><p>{c.hypothesis}</p><small>공개 제품 속성과 자료를 연결한 사전 작성 가설입니다.</small></section>
      <section className="card-section"><div className="eyebrow">진입 부담·반대 근거</div><p>{c.counter}</p></section>
      <details className="source-details"><summary>소비 근거와 출처 {c.signal_sources.length}건</summary><Sources items={evidence.filter(e => c.signal_sources.includes(e.id))} /></details>
    </> : <div className="gap-list">
      <p className="gap-intro">무엇이 확인되면 다음 판단으로 넘어갈 수 있을까요?</p>
      {c.missing.map((gap, i) => <section className="gap" key={gap.item}><h4><span>0{i + 1}</span> {gap.item}</h4>
        <dl><dt>필요한 자료</dt><dd>{gap.needed}</dd><dt>확보처</dt><dd>{gap.provider}</dd><dt>해소 조건</dt><dd>{gap.condition}</dd></dl>
        <small>{gap.basis}</small>{gap.url && <a href={gap.url} target="_blank" rel="noreferrer">소관 기관 확인 ↗</a>}
      </section>)}
    </div>}
  </article>
}

function App() {
  const [product, setProduct] = useState<Product | null>(null)
  const [history, setHistory] = useState<History[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    Promise.all([api<Product>('/product'), api<History[]>('/runs')]).then(([p, h]) => {
      if (active) { setProduct(p); setHistory(h) }
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [])

  async function load(id?: string) {
    setBusy(true); setError('')
    try {
      const result = id ? await api<Run>(`/runs/${id}`) : await api<Run>('/runs', 'POST')
      setRun(result)
      if (!id) setHistory(h => [{ id: result.id, created_at: result.created_at, product_version: result.product.version }, ...h].slice(0, 100))
    } catch (e) { setError(e instanceof Error ? e.message : '결과를 불러오지 못했습니다.') }
    finally { setBusy(false) }
  }
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" aria-label="Market Compass 처음으로"><span className="brand-mark" aria-hidden="true">M</span> Market Compass</a><span className="local-pill"><i /> 로컬 프로토타입</span></header>
    <div className="layout">
      <aside className="sidebar">
        <p className="sidebar-label">WORKSPACE</p><div className="nav-active"><span aria-hidden="true">◈</span> 수출 기회 탐색</div>
        <div className="history-title"><span>저장된 실행</span><span>{history.length}</span></div>
        <nav aria-label="저장된 실행 이력">{history.length === 0 ? <p className="empty-history">첫 비교를 실행하면<br />이곳에서 다시 열 수 있어요.</p> : history.map(h => <button disabled={busy} className={`history-item ${run?.id === h.id ? 'selected' : ''}`} key={h.id} onClick={() => load(h.id)}><strong>빠다코코낫 · 2개국</strong><small>{date(h.created_at)}</small></button>)}</nav>
        <div className="sidebar-footer"><span className="status-dot" /> 로컬 저장 사용<p>로그인과 외부 DB 연결 없이<br />시험 결과를 보관합니다.</p></div>
      </aside>
      <main>
        <div className="breadcrumb">WORKSPACE <span>/</span> 기회 탐색</div>
        <div className="page-heading"><div><h1>수출 기회 검토</h1><p className="subtitle">제품별 시장 통계와 소비 근거를 비교합니다.</p></div><span className="edition">공개자료 연결 시험<br /><strong>2022–2024 · HS 190531</strong></span></div>
        <section className="trial-banner"><span className="badge">연결 시험</span><p>빠다코코낫 × 호주·일본 · 2022–2024<br /><small>보관된 실제 통계와 사전 검토 근거를 연결합니다. 자동 국가 발굴·AI 분석·최종 추천은 아직 제공하지 않습니다.</small></p></section>
        {error && <div role="alert" className="error"><strong>작업을 완료하지 못했어요.</strong> {error}</div>}
        <section className="product-panel" aria-label="분석 제품과 실행 조건">
          <div className="product-art" aria-hidden="true">P01</div>
          <div className="product-copy"><div className="eyebrow">{product?.group ?? '제품 불러오는 중'} <span className="badge">실제 제품</span></div><h2>{product?.name ?? '빠다코코낫'}</h2><p>{product?.description ?? '공개 제품 정보를 불러오고 있습니다.'}</p><small>{product?.packaging} · {product?.note}</small></div>
          <div className="run-controls"><span>고정 2개국 · 공통 3개년</span><button className="primary" disabled={busy || !product} onClick={() => load()}>{busy ? '자료 연결 중…' : '비교 실행 · 로컬 저장'} <span aria-hidden="true">↗</span></button><small>API 키 없이 실행할 수 있어요</small></div>
        </section>
        {run ? <section className="results" aria-label="국가별 시험 결과" aria-busy={busy}>
          <div className="summary-grid"><div><small>검토 제품</small><strong>{run.product.name}</strong></div><div><small>시험 대상</small><strong>{run.countries.length}<span>개국</span></strong></div><div><small>통계 기간</small><strong>2022–2024</strong></div><div><small>결과 구분</small><strong>연결 시험<span>순위 미산정</span></strong></div></div>
          <div className="section-heading"><div><h2>국가별 비교</h2></div><span className="saved-label">저장됨 · {date(run.created_at)}</span></div>
          <div className="result-notice">두 국가는 검증용 사례입니다. 국가 간 시장 우열과 순위는 산정하지 않았습니다. 직접 구매 근거가 부족해도 탐색 후보는 유지합니다.</div>
          <div className="country-grid">{run.countries.map(c => <CountryCard key={`${run.id}-${c.reporter_code}`} country={c} evidence={run.evidence} />)}</div>
          <details className="run-details"><summary>이번 실행의 조건·제품 출처·분석 한계</summary><p>제품 버전 {run.product.version} · 실행 ID {run.id}</p><p>{run.product.note}</p><ul>{run.limitations.map(l => <li key={l}>{l}</li>)}</ul><Sources items={run.evidence.filter(e => ['product', 'label'].includes(e.id))} /></details>
        </section> : <section className="onboarding" aria-label="실행 안내"><h2>첫 비교 실행</h2><p className="subtitle">위 버튼을 누르면 아래 순서로 자료를 연결하고 결과를 저장합니다.</p><div className="steps"><div><span>01</span><h3>시장 상황 확인</h3><p>보관한 무역통계로 성장 지표를<br />다시 계산합니다.</p></div><div><span>02</span><h3>제품과 연결</h3><p>사전 검토한 소비자료와 제품 속성을<br />구분해 함께 보여줍니다.</p></div><div><span>03</span><h3>다음 확인 찾기</h3><p>반대 근거와 필요한 자료를 남기고<br />결과를 로컬에 저장합니다.</p></div></div></section>}
        <footer className="main-footer">Market Compass <span>개인 학습용 프로토타입 · 실제 수출 적합성 판정이 아닙니다.</span></footer>
      </main>
    </div>
  </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
