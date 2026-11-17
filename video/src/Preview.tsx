import React, {useLayoutEffect, useRef} from 'react';
import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';

type Case = {label: string; gel: number; plf: number; gain: number; revenu: number};
export type PreviewData = {
  summary: {taille_echantillon: number; source_ref: string; statut_calage: string; gain_ir_max_eur: number; gain_ir_min_eur: number};
  points: [number, number][];
  cases: Case[];
};

const palette = {paper: '#F4F2EC', ink: '#0F1115', grid: '#D8D4C8', gain: '#00C853', loss: '#FF3D00', caution: '#FFE600'};
const number = new Intl.NumberFormat('fr-FR');
const euros = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0});
const signedEuros = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0, signDisplay: 'exceptZero'});
const safe = {position: 'absolute' as const, left: 70, top: 180, width: 850, height: 1320};
const heading = {fontFamily: 'Space Grotesk', fontWeight: 700, fontSize: 96, lineHeight: .98, letterSpacing: '-.03em', margin: 0};
const mono = {fontFamily: 'JetBrains Mono', fontVariantNumeric: 'tabular-nums', fontSize: 36};
const sans = {fontFamily: 'Space Grotesk', fontWeight: 600, fontSize: 45};

function Cloud({points}: Pick<PreviewData, 'points'>) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const ref = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const ctx = ref.current?.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, 850, 630);
    const shift = Math.min(1, frame / (fps * 1.7));
    for (let i = 0; i < points.length; i++) {
      const [decile, gain] = points[i];
      const jitter = ((Math.imul(i + 1, 2654435761) >>> 0) / 4294967296) - .5;
      const verticalJitter = ((Math.imul((i + 1) ^ ((i + 1) >>> 4), 1597334677) >>> 0) / 4294967296) - .5;
      const x = 40 + (decile - 1) * 81 + jitter * 56;
      const spread = Math.sign(gain) * Math.log1p(Math.abs(gain)) * 29;
      const y = 315 - spread * shift + verticalJitter * (gain === 0 ? 48 : 76);
      ctx.fillStyle = shift < Math.abs(jitter) || gain === 0 ? '#888B91' : gain > 0 ? palette.gain : palette.loss;
      ctx.fillRect(x, y, 4, 4);
    }
  }, [frame, fps, points]);
  return <canvas aria-label="Distribution expérimentale des gains et pertes d’impôt" ref={ref} width={850} height={630} />;
}

function Ticket({result}: {result: Case}) {
  return <AbsoluteFill style={{background: palette.paper, color: palette.ink}}>
    <div style={safe}>
      <p style={{...mono, margin: '0 0 40px'}}>PLF 2027 DÉPOSÉ · IMPÔT SUR LE REVENU</p>
      <h2 style={heading}>{result.label}</h2>
      <p style={{...sans, marginTop: 45}}>{euros.format(result.revenu)} de revenu annuel imputé</p>
      <div style={{...mono, borderBlock: '4px dashed #999488', margin: '70px 0 50px', padding: '30px 0', lineHeight: 2.2}}>
        <div style={{display: 'flex', justifyContent: 'space-between'}}><span>Barème gelé</span><b>{euros.format(result.gel)}</b></div>
        <div style={{display: 'flex', justifyContent: 'space-between'}}><span>PLF déposé</span><b>{euros.format(result.plf)}</b></div>
      </div>
      <strong style={{...mono, display: 'inline-block', background: result.gain > 0 ? palette.gain : palette.loss,
        color: palette.ink, padding: '12px 20px', fontSize: 62}}>
        {euros.format(Math.abs(result.gain))} d’impôt en {result.gain > 0 ? 'moins' : 'plus'}
      </strong>
      <p style={{...mono, marginTop: 54}}>Cas synthétique · montants annuels</p>
    </div>
  </AbsoluteFill>;
}

function Opening({data}: {data: PreviewData}) {
  const frame = useCurrentFrame();
  const legend = Math.max(0, Math.min(1, (frame - 14) / 5));
  return <AbsoluteFill style={{background: palette.ink, color: palette.paper}}>
    <div style={safe}>
      <h1 style={heading}>Qui paierait plus<br/>d’impôt&nbsp;?</h1>
      <p style={{...sans, marginBottom: 10}}>{number.format(data.points.length)} ménages synthétiques</p>
      <Cloud points={data.points}/>
      <div style={{...mono, display: 'flex', justifyContent: 'space-between', fontSize: 32}}>
        <span>D1</span><span>D10</span>
      </div>
      <div style={{...sans, opacity: legend, display: 'flex', flexDirection: 'column', gap: 9, marginTop: 28, fontSize: 43}}>
        <span style={{color: palette.gain}}>VERT · Jusqu’à {signedEuros.format(data.summary.gain_ir_max_eur)}/an</span>
        <span style={{color: '#FF784E'}}>ROUGE · Jusqu’à {signedEuros.format(data.summary.gain_ir_min_eur)}/an</span>
      </div>
    </div>
  </AbsoluteFill>;
}

export function Preview({data}: {data: PreviewData}) {
  const {fps} = useVideoConfig();
  return <AbsoluteFill>
    <Sequence durationInFrames={3 * fps}>
      <Opening data={data}/>
    </Sequence>
    {data.cases.map((result, i) => <Sequence key={result.label} from={(3 + 13 * i) * fps} durationInFrames={13 * fps}>
      <Ticket result={result}/>
    </Sequence>)}
    <Sequence from={42 * fps}>
      <AbsoluteFill style={{background: palette.ink, color: palette.paper}}>
        <div style={safe}>
          <span style={{...mono, display: 'inline-block', background: palette.caution, color: palette.ink, padding: '15px 20px'}}>
            🟡 CHIFFRAGE EXPÉRIMENTAL
          </span>
          <h2 style={{...heading, marginTop: 65}}>Les sources<br/>du calcul</h2>
          <p style={sans}>OpenFisca-France · Loi simulée sur les revenus 2026</p>
          <p style={sans}>PLF 2027 déposé · Articles 2 et 3 · AN n° 3210</p>
          <p style={sans}>Population synthétique · Insee et DGFiP · 2023</p>
          <p style={{...mono, fontSize: 28}}>Simulation ex ante. Les résultats nationaux restent à valider.</p>
        </div>
      </AbsoluteFill>
    </Sequence>
  </AbsoluteFill>;
}
