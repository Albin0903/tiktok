import {ImageResponse} from "next/og";
import {describeTaxChange} from "../../tax-change";

const api = process.env.API_URL ?? "http://127.0.0.1:8000";
const euros = new Intl.NumberFormat("fr-FR", {style: "currency", currency: "EUR", maximumFractionDigits: 0});

export async function POST(request: Request) {
  let response: Response;
  try {
    const profile = await request.json();
    response = await fetch(`${api}/api/simulate`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(profile),
      cache: "no-store",
    });
  } catch {
    return Response.json({detail: "Simulation indisponible"}, {status: 503});
  }
  if (!response.ok) return Response.json({detail: "Profil invalide ou simulation indisponible"}, {status: response.status});
  const result = await response.json();
  const ir = result.lignes.find((line: {poste: string}) => line.poste === "impot_revenu");
  if (!ir) return Response.json({detail: "Résultat d’IR absent"}, {status: 502});
  const change = describeTaxChange(ir.delta_eur);
  return new ImageResponse(
    <div style={{width: "100%", height: "100%", display: "flex", flexDirection: "column", background: "#f4f2ec",
      color: "#0f1115", padding: "180px 140px 380px 84px", fontFamily: "sans-serif"}}>
      <span style={{fontSize: 40}}>VÉRITÉ FISCALE 2027</span>
      <span style={{fontSize: 116, fontWeight: 700, marginTop: 115, lineHeight: 1}}>Ma Carte 2027</span>
      <span style={{fontSize: 42, marginTop: 48}}>Impôt sur le revenu 2026</span>
      <div style={{display: "flex", flexDirection: "column", gap: 22, fontSize: 45, marginTop: 76,
        padding: 40, borderTop: "3px dashed #0f1115", borderBottom: "3px dashed #0f1115"}}>
        <span>Barème gelé · {euros.format(ir.gel_eur)}</span>
        <span>PLF déposé · {euros.format(ir.plf_eur)}</span>
        <span style={{fontWeight: 700}}>{change.annual}</span>
        {change.monthly && <span style={{fontSize: 34}}>{change.monthly}</span>}
      </div>
      <span style={{fontSize: 34, marginTop: 56, background: "#ffe600", padding: "12px 18px"}}>Hypothèses de chiffrage</span>
      <span style={{fontSize: 31, marginTop: 42}}>OpenFisca · PLF 2027, articles 2 et 3</span>
      <span style={{fontSize: 24, marginTop: 20}}>Simulation pédagogique · montant indicatif</span>
    </div>,
    {width: 1080, height: 1920},
  );
}
